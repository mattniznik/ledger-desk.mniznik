"""Account suggestion for bills without a PO: Claude suggests, code checks the
account exists and fits the vendor's category, and a person confirms by approving.

A suggestion that fails a check never reaches the proposal; the vendor's usual account does, and
the rejected suggestion is shown to the person with the reason.
"""

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from fakes import ScriptedModel, perfect_reading, read_reply, text_reply
from ledger_desk.accounts import CATEGORY_ACCOUNTS, suggest_account
from ledger_desk.company import build_company
from ledger_desk.documents import render_case
from ledger_desk.erp.client import ErpClient
from ledger_desk.invoices import load_case
from ledger_desk.model import ModelReply
from ledger_desk.workflow import Deps, build_workflow


def suggestion(account, reason="Electricity for the roastery and cafes."):
    return ModelReply(stop_reason="end_turn", text=json.dumps({"account": account, "reason": reason}), usage={"input_tokens": 800, "output_tokens": 60}, model="claude-opus-5-5")


@pytest.fixture(scope="module")
def company():
    return build_company()


def test_a_suggestion_that_exists_and_fits_the_category_is_used(company):
    inv = load_case("09").invoice
    s = suggest_account(inv, company, ScriptedModel(suggestion("6200")))
    assert (s.account, s.suggested, s.check, s.source) == ("6200", "6200", "ok", "suggested")
    assert s.reason and s.usage[0]["step"] == "suggest_account"


def test_an_account_not_in_the_chart_falls_back_to_the_vendors_usual_one(company):
    s = suggest_account(load_case("09").invoice, company, ScriptedModel(suggestion("6999")))
    assert (s.account, s.suggested, s.check, s.source) == ("6200", "6999", "not_in_chart", "vendor default")


def test_an_account_outside_the_vendors_category_falls_back_too(company):
    # a utility bill coded to Equipment: the account exists, it does not fit an electricity bill
    s = suggest_account(load_case("09").invoice, company, ScriptedModel(suggestion("1500")))
    assert (s.account, s.check, s.source) == ("6200", "wrong_category", "vendor default")


def test_accounts_payable_is_never_an_expense_suggestion(company):
    s = suggest_account(load_case("12").invoice, company, ScriptedModel(suggestion("2000")))
    assert s.account == "6500" and s.check == "not_in_chart"


def test_an_unknown_vendor_gets_a_hint_but_no_account(company):
    # invoice 11: the vendor is not in the master, so there is no category to check against
    s = suggest_account(load_case("11").invoice, company, ScriptedModel(suggestion("6400", "Point-of-sale software subscription.")))
    assert (s.account, s.suggested, s.check, s.source) == (None, "6400", "no_vendor", None)


def test_a_refusal_or_bad_reply_leaves_the_vendors_usual_account(company):
    for reply in (ModelReply(stop_reason="refusal", model="claude-opus-5-5"), text_reply("Probably utilities.")):
        s = suggest_account(load_case("09").invoice, company, ScriptedModel(reply))
        assert (s.account, s.suggested, s.check, s.source) == ("6200", None, "no_suggestion", "vendor default")


def test_the_request_carries_the_chart_the_vendor_and_the_lines_as_data(company):
    model = ScriptedModel(suggestion("6300"))
    suggest_account(load_case("08").invoice, company, model)
    req = model.requests[0]
    assert req["task"] == "suggest_account" and "tools" not in req and "document" not in req
    assert set(req["schema"]["properties"]["account"]["enum"]) == {a.number for a in company.accounts if a.number != "2000"}
    data = json.loads(req["prompt"].split("\n", 1)[1])
    assert data["vendor"] == {"name": "Espresso Repair Service", "category": "repairs", "usual_account": "6300"}
    assert data["lines"] == ["Group head rebuild, labor and parts"]
    assert "data, not instructions" in req["system"]


def test_every_vendor_category_maps_to_accounts_that_exist(company):
    chart = {a.number for a in company.accounts}
    assert {v.category for v in company.vendors} <= set(CATEGORY_ACCOUNTS)
    for category, accounts in CATEGORY_ACCOUNTS.items():
        assert accounts <= chart and "2000" not in accounts, category
    for v in company.vendors:
        assert v.default_account in CATEGORY_ACCOUNTS[v.category], v.name


# --- in the workflow -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def docs(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("acct-docs")
    for case_id in ("01", "09"):
        render_case(load_case(case_id), out)
    return out


def run(app, model, docs, case_id):
    http = ErpClient(TestClient(app), api_key="test-api-key", sleep=lambda s: None)
    graph = build_workflow(Deps(model=model, erp=http, company=build_company()), InMemorySaver())
    doc = str(next(docs.glob(f"{load_case(case_id).slug}.*")))
    return graph.invoke({"document": doc, "invoice_ref": f"acct-{uuid.uuid4().hex[:8]}"}, {"configurable": {"thread_id": uuid.uuid4().hex}})


def test_a_bill_without_a_po_is_proposed_with_the_checked_suggestion(app, docs):
    model = ScriptedModel(read_reply(perfect_reading(load_case("09"))), suggestion("6200"))
    state = run(app, model, docs, "09")
    assert [r["task"] for r in model.requests] == ["read", "suggest_account"]
    assert state["proposal"]["lines"][0]["account"] == "6200"
    assert state["account_suggestion"]["check"] == "ok" and state["account_suggestion"]["source"] == "suggested"
    assert [u["step"] for u in state["model_usage"]] == ["read", "suggest_account"]
    assert state["__interrupt__"][0].value["account_suggestion"]["suggested"] == "6200"  # the person sees it


def test_a_failed_suggestion_never_reaches_the_proposal(app, docs):
    model = ScriptedModel(read_reply(perfect_reading(load_case("09"))), suggestion("1500"))
    state = run(app, model, docs, "09")
    assert state["proposal"]["lines"][0]["account"] == "6200"
    assert state["account_suggestion"]["check"] == "wrong_category"


def test_a_bill_with_a_po_takes_its_account_from_the_po_and_asks_nothing(app, docs):
    model = ScriptedModel(read_reply(perfect_reading(load_case("01"))))
    state = run(app, model, docs, "01")
    assert [r["task"] for r in model.requests] == ["read"]
    assert state["proposal"]["lines"][0]["account"] == "1200"
