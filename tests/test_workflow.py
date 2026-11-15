"""The LangGraph workflow: read, check, investigate, propose, pause for a person, post.

The approval pause is `interrupt()`; resuming re-runs the paused node from its start (LangGraph
interrupts docs), so posting is its own node after it and carries an idempotency key made from the
invoice and the approval signature. The re-run test crashes the run right after the ERP has
written the entry and runs it again: still exactly one entry.
"""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from conftest import entries_for
from fakes import ScriptedModel, perfect_reading, read_reply, text_reply
from ledger_desk.approval import sign
from ledger_desk.company import build_company
from ledger_desk.documents import render_case
from ledger_desk.erp.client import ErpClient
from ledger_desk.invoices import load_case
from ledger_desk.model import ModelReply
from ledger_desk.workflow import Deps, build_workflow


@pytest.fixture(scope="module")
def docs(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("wf-docs")
    for case_id in ("03", "04", "13"):
        render_case(load_case(case_id), out)
    return out


def path_of(docs, case_id):
    return str(next(docs.glob(f"{load_case(case_id).slug}.*")))


def deps(app, model, **extra):
    http = ErpClient(TestClient(app), api_key="test-api-key", sleep=lambda s: None)
    return Deps(model=model, erp=http, company=build_company(), **extra)


def start(graph, document, ref):
    config = {"configurable": {"thread_id": f"run-{uuid.uuid4().hex}"}}
    state = graph.invoke({"document": document, "invoice_ref": ref}, config)
    return state, config


def approval_for(state, keys, approver="clerk", decision="approve", reason="checked"):
    lines = state["proposal"]["lines"]
    return {"decision": decision, "approver": approver, "reason": reason, "signature": sign(keys.private, state["invoice_ref"], approver, lines)}


def test_a_clean_invoice_pauses_for_approval_and_posts_once(app, erp_db, keys, docs, ref):
    model = ScriptedModel(read_reply(perfect_reading(load_case("13"))))
    graph = build_workflow(deps(app, model), InMemorySaver())
    state, config = start(graph, path_of(docs, "13"), ref)
    assert state["status"] == "ready" and "__interrupt__" in state
    assert state["proposal"]["lines"][0]["account"] == "1500"
    final = graph.invoke(Command(resume=approval_for(state, keys, approver="controller")), config)
    assert final["status"] == "posted" and final["entry_id"]
    assert entries_for(erp_db, ref) == 1


def test_a_reading_whose_totals_do_not_add_up_is_an_exception_never_ready(app, docs, ref):
    model = ScriptedModel(read_reply(perfect_reading(load_case("04"))), text_reply("The lines add up to $665.00, not $755.00."))
    graph = build_workflow(deps(app, model), InMemorySaver())
    state, _ = start(graph, path_of(docs, "04"), ref)
    assert state["status"] == "exception"
    assert "TOTALS_MISMATCH" in [f["code"] for f in state["flags"]]


def test_a_misread_total_becomes_an_exception_too(app, docs, ref):
    misread = perfect_reading(load_case("03"), total="2010.00")
    model = ScriptedModel(read_reply(misread), text_reply("The total read does not match the document."))
    graph = build_workflow(deps(app, model), InMemorySaver())
    state, _ = start(graph, path_of(docs, "03"), ref)
    codes = {f["code"] for f in state["flags"]}
    assert state["status"] == "exception"
    assert {"TOTALS_MISMATCH", "SOURCE_NOT_FOUND"} <= codes


def test_a_refusal_sends_the_invoice_to_manual_entry_and_never_pauses(app, docs, ref):
    model = ScriptedModel(ModelReply(stop_reason="refusal", model="claude-opus-5-5"))
    graph = build_workflow(deps(app, model), InMemorySaver())
    state, _ = start(graph, path_of(docs, "03"), ref)
    assert state["status"] == "manual_entry"
    assert "__interrupt__" not in state


def test_resuming_after_approval_posts_once_even_if_the_step_re_runs(app, erp_db, keys, docs, ref):
    crashes = []

    def crash_once_after_posting(entry_id):
        if not crashes:
            crashes.append(entry_id)
            raise RuntimeError("worker died after the ERP wrote the entry")

    model = ScriptedModel(read_reply(perfect_reading(load_case("03"))), text_reply("Billed $0.42 against $0.38 (+$200.00)."))
    graph = build_workflow(deps(app, model, after_post=crash_once_after_posting), InMemorySaver())
    state, config = start(graph, path_of(docs, "03"), ref)
    assert state["status"] == "exception"
    with pytest.raises(RuntimeError, match="worker died"):
        graph.invoke(Command(resume=approval_for(state, keys)), config)
    final = graph.invoke(None, config)  # LangGraph runs the failed step again
    assert final["status"] == "posted"
    assert final["entry_id"] == crashes[0]
    assert entries_for(erp_db, ref) == 1


def test_a_rejection_posts_nothing(app, erp_db, keys, docs, ref):
    model = ScriptedModel(read_reply(perfect_reading(load_case("13"))))
    graph = build_workflow(deps(app, model), InMemorySaver())
    state, config = start(graph, path_of(docs, "13"), ref)
    final = graph.invoke(Command(resume=approval_for(state, keys, decision="reject", reason="duplicate of a paper copy")), config)
    assert final["status"] == "rejected"
    assert entries_for(erp_db, ref) == 0


def test_run_metrics_add_up_every_model_call(app, keys, docs, ref):
    model = ScriptedModel(read_reply(perfect_reading(load_case("03"))), text_reply("Price variance of $200.00."))
    graph = build_workflow(deps(app, model), InMemorySaver())
    state, _ = start(graph, path_of(docs, "03"), ref)
    m = state["metrics"]
    assert m["model_calls"] == 2
    assert m["input_tokens"] == 3000 + 1500 and m["output_tokens"] == 600 + 200
    # Opus 5.5: $4 per million input, $20 per million output (Anthropic pricing page, 2026-11-12)
    assert m["cost_usd"] == pytest.approx((4500 * 4 + 800 * 20) / 1_000_000)


def test_a_run_paused_for_approval_survives_a_restart_with_postgres_checkpoints(app, erp_db, keys, docs, ref):
    from langgraph.checkpoint.postgres import PostgresSaver

    from ledger_desk.db import url_for

    url = url_for(erp_db)
    model = ScriptedModel(read_reply(perfect_reading(load_case("13"))))
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()
        state, config = start(build_workflow(deps(app, model), saver), path_of(docs, "13"), ref)
    # A new process: a new graph and a new connection, the same thread id.
    with PostgresSaver.from_conn_string(url) as saver:
        final = build_workflow(deps(app, model), saver).invoke(Command(resume=approval_for(state, keys, approver="controller")), config)
    assert final["status"] == "posted"
    assert entries_for(erp_db, ref) == 1
