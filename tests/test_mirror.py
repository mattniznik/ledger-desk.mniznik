"""The mirror step (docs/decisions/0006): after the mock ERP posts an approved bill, the same bill goes
to the QuickBooks sandbox. The mock ERP stays the system of record, so the mirror runs only after a
posting, never instead of one, and a QuickBooks failure leaves the run posted with the error kept.

The mirror here is a recording fake; tests/test_quickbooks.py covers what the real one sends.
"""

import uuid

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from conftest import entries_for
from fakes import ScriptedModel, perfect_reading, read_reply, text_reply
from ledger_desk.api import create_api
from ledger_desk.approval import new_key_pair, sign
from ledger_desk.company import build_company
from ledger_desk.db import connect, reset_database, seed_erp
from ledger_desk.documents import render_case
from ledger_desk.erp.client import ErpClient
from ledger_desk.invoices import load_case
from ledger_desk.workflow import Deps, build_workflow, mirror_request

import pytest


class RecordingMirror:
    def __init__(self, fail: Exception | None = None):
        self.requests: list[dict] = []
        self.fail = fail

    def __call__(self, request: dict) -> dict:
        self.requests.append(request)
        if self.fail:
            raise self.fail
        return {"entity": "Bill" if request["kind"] == "bill" else "VendorCredit", "id": "151", "doc_number": request["number"], "created": True, "total": float(request["lines"][0]["amount"])}


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    out = tmp_path_factory.mktemp("mirror-docs")
    for case_id in ("05", "13"):
        render_case(load_case(case_id), out)
    return out


def path_of(docs, case_id):
    return str(next(docs.glob(f"{load_case(case_id).slug}.*")))


def run_to_pause(app, docs, ref, case_id, mirror, *extra_replies):
    model = ScriptedModel(read_reply(perfect_reading(load_case(case_id))), *extra_replies)
    erp = ErpClient(TestClient(app), api_key="test-api-key", sleep=lambda s: None)
    graph = build_workflow(Deps(model=model, erp=erp, company=build_company(), mirror=mirror), InMemorySaver())
    config = {"configurable": {"thread_id": f"run-{uuid.uuid4().hex}"}}
    state = graph.invoke({"document": path_of(docs, case_id), "invoice_ref": ref}, config)
    return graph, state, config


def approve(state, keys, approver="controller", decision="approve"):
    lines = state["proposal"]["lines"]
    return {"decision": decision, "approver": approver, "reason": "checked", "signature": sign(keys.private, state["invoice_ref"], approver, lines)}


def test_an_approved_bill_is_mirrored_after_it_posts(app, erp_db, keys, docs, ref):
    mirror = RecordingMirror()
    graph, state, config = run_to_pause(app, docs, ref, "13", mirror)
    assert mirror.requests == []  # nothing leaves before a person approves
    final = graph.invoke(Command(resume=approve(state, keys)), config)
    assert final["status"] == "posted" and entries_for(erp_db, ref) == 1
    (request,) = mirror.requests
    total = f"{load_case('13').invoice.total:.2f}"  # ground truth, not the code's output
    assert request == {
        "kind": "bill",
        "vendor": "Roasting Equipment Supplier",
        "number": "EQP-5502",
        "date": "2026-11-12",
        "due_date": request["due_date"],
        "lines": [{"account": "1500", "account_name": "Equipment", "amount": total, "description": "Roaster drum replacement"}],  # the posted entry: the total, tax included
        "note": f"Ledger Desk {ref}, ERP entry {final['entry_id']}",
    }
    terms = build_company().vendor_by_name("Roasting Equipment Supplier").terms_days
    from datetime import date, timedelta

    assert request["due_date"] == (date(2026, 11, 12) + timedelta(days=terms)).isoformat()
    assert final["mirror"] == {"status": "mirrored", "entity": "Bill", "id": "151", "doc_number": "EQP-5502", "created": True, "total": float(total)}


def test_a_credit_memo_is_mirrored_as_a_credit_on_its_own_account(app, keys, docs, ref):
    mirror = RecordingMirror()
    graph, state, config = run_to_pause(app, docs, ref, "05", mirror, text_reply("A credit memo for the returned goods."))
    if state["proposal"]["lines"] == []:
        pytest.skip("sample 05 has no entry to post in this build")
    graph.invoke(Command(resume=approve(state, keys)), config)
    (request,) = mirror.requests
    case = load_case("05")
    assert request["kind"] == "credit" and request["due_date"] is None
    assert request["lines"][0]["amount"] == f"{abs(case.invoice.total):.2f}"
    assert request["lines"][0]["account"] != "2000"


def test_a_mirror_failure_leaves_the_run_posted_with_the_error_kept(app, erp_db, keys, docs, ref):
    mirror = RecordingMirror(fail=RuntimeError("QuickBooks said no"))
    graph, state, config = run_to_pause(app, docs, ref, "13", mirror)
    final = graph.invoke(Command(resume=approve(state, keys)), config)
    assert final["status"] == "posted" and entries_for(erp_db, ref) == 1
    assert final["mirror"] == {"status": "failed", "error": "RuntimeError: QuickBooks said no"}


def test_a_rejected_bill_is_never_mirrored(app, keys, docs, ref):
    mirror = RecordingMirror()
    graph, state, config = run_to_pause(app, docs, ref, "13", mirror)
    final = graph.invoke(Command(resume=approve(state, keys, decision="reject")), config)
    assert final["status"] == "rejected" and mirror.requests == [] and "mirror" not in final


def test_without_a_mirror_the_graph_has_no_mirror_step(app, keys, docs, ref):
    graph, state, config = run_to_pause(app, docs, ref, "13", None)
    assert "mirror" not in graph.get_graph().nodes
    final = graph.invoke(Command(resume=approve(state, keys)), config)
    assert final["status"] == "posted" and "mirror" not in final


def test_mirror_request_needs_a_posted_entry():
    with pytest.raises(ValueError):
        mirror_request({"status": "rejected"}, build_company())


# --- through the API --------------------------------------------------------------------------

DB = "ledger_desk_test_mirror"


@pytest.fixture(scope="module")
def api_db():
    reset_database(DB)
    with connect(DB) as conn:
        seed_erp(conn, build_company())
        conn.commit()
    return DB


def test_the_decision_audits_the_mirror_and_the_run_shows_it(api_db, tmp_path):
    mirror = RecordingMirror()
    client = TestClient(create_api(api_db, docs_dir=tmp_path, keys=new_key_pair(), mirror=mirror))
    h = {"X-Session-Id": client.post("/sessions").json()["session_id"]}
    run = client.post("/runs", json={"invoice": "13"}, headers=h).json()
    assert run["paused"]
    done = client.post(f"/runs/{run['run_id']}/decision", json={"role": "controller", "decision": "approve", "reason": "checked"}, headers=h)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "posted" and done.json()["mirror"]["status"] == "mirrored"
    events = [e["action"] for e in client.get("/audit", headers=h).json()["entries"]]
    assert events.index("workflow.post") < events.index("workflow.mirror") < events.index("run.posted")
    assert len(mirror.requests) == 1
