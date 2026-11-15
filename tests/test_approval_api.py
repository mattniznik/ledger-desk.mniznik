"""The approval endpoint: who may approve what is enforced by the API, not by hiding
a button. The API holds the private key; it signs only an approval that passes the rules, and
the ERP posts only a signed entry.

Three refusals matter most: a clerk approving $5,000 or more gets a 403; a bank-change approval
without the phone box gets a 400; an override (approving with a flag open) without a reason gets
a 400. Every refusal is written to the audit log too, so a refused attempt is on record.
"""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ledger_desk.api import create_api
from ledger_desk.approval import new_key_pair, verify
from ledger_desk.authority import Refusal, check_decision
from ledger_desk.company import build_company
from ledger_desk.db import connect, reset_database, seed_erp

DB = "ledger_desk_test_api_approval"
REPLAYS = Path(__file__).resolve().parents[1] / "replays" / "claude-opus-5-5-low-run2"


# --- the rules, as a pure function --------------------------------------------------------------

def pause(approver="clerk", status="ready", controller_only=False, total="1140.00", lines=True):
    return {"approver": approver, "status": status, "controller_only": controller_only, "total": total,
            "proposal": {"lines": [{"account": "6200", "debit": total, "credit": "0.00"}, {"account": "2000", "debit": "0.00", "credit": total}] if lines else []}}


@pytest.mark.parametrize(
    "p, kw, code",
    [
        (pause(approver="controller", total="13423.00"), dict(role="clerk"), 403),
        (pause(total="5000.00"), dict(role="clerk"), 403),  # the limit holds even if the pause said clerk
        (pause(total="4999.99"), dict(role="clerk"), None),
        (pause(approver="controller", status="exception", controller_only=True, total="860.00"), dict(role="controller", reason="called them"), 400),
        (pause(approver="controller", status="exception", controller_only=True, total="860.00"), dict(role="clerk", reason="x", phone_confirmed=True), 403),
        (pause(approver="controller", status="exception", controller_only=True, total="860.00"), dict(role="controller", reason="called the number on file", phone_confirmed=True), None),
        (pause(status="exception"), dict(role="clerk", reason="  "), 400),
        (pause(status="exception"), dict(role="clerk", reason="price agreed by phone"), None),
        (pause(status="exception", lines=False), dict(role="clerk", reason="x"), 400),
        (pause(approver="controller", total="13423.00"), dict(role="clerk", decision="reject"), None),  # anyone may reject
        (pause(), dict(role="auditor"), 422),
    ],
    ids=["clerk-over-limit", "clerk-at-5000", "clerk-under-limit", "bank-no-phone", "bank-clerk", "bank-ok",
         "override-blank-reason", "override-with-reason", "no-entry-to-post", "reject-needs-no-authority", "unknown-role"],
)
def test_who_may_decide_what(p, kw, code):
    kw = {"decision": "approve", "reason": "", "phone_confirmed": False, **kw}
    r = check_decision(p, **kw)
    assert (r.status if r else None) == code, r


# --- through the API ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db():
    reset_database(DB)
    with connect(DB) as conn:
        seed_erp(conn, build_company())
        conn.commit()
    return DB


@pytest.fixture(scope="module")
def keys():
    return new_key_pair()


@pytest.fixture
def client(db, keys, tmp_path):
    return TestClient(create_api(db, docs_dir=tmp_path, replays_dir=REPLAYS, keys=keys))


def start(client, invoice):
    h = {"X-Session-Id": client.post("/sessions").json()["session_id"]}
    run = client.post("/runs", json={"invoice": invoice}, headers=h).json()
    return h, run


def decide(client, h, run, **body):
    return client.post(f"/runs/{run['run_id']}/decision", json=body, headers=h)


def posted(db, ref):
    with connect(db) as conn:
        return conn.execute("SELECT count(*) FROM erp.journal_entries WHERE invoice_ref = %s", (ref,)).fetchone()[0]


def test_a_clerk_approving_5000_or_more_gets_a_403_and_nothing_posts(client, db):
    h, run = start(client, "13")  # $13,423.00, capital
    r = decide(client, h, run, role="clerk", decision="approve")
    assert r.status_code == 403
    assert posted(db, run["invoice_ref"]) == 0
    assert client.get(f"/runs/{run['run_id']}", headers=h).json()["paused"] is True
    last = client.get("/audit", headers=h).json()["entries"][-1]
    assert (last["actor"], last["action"], last["detail"]["status"]) == ("person", "approval.refused", 403)


def test_the_controller_approves_it_and_it_posts_exactly_once_with_a_valid_signature(client, db, keys):
    h, run = start(client, "13")
    r = decide(client, h, run, role="controller", decision="approve")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "posted" and body["entry_id"] and body["paused"] is False
    assert posted(db, run["invoice_ref"]) == 1
    with connect(db) as conn:
        sig, role = conn.execute("SELECT signature, role FROM app.approvals WHERE session_id = %s", (h["X-Session-Id"],)).fetchone()
    lines = run["pause"]["proposal"]["lines"]
    assert role == "controller" and verify(keys.public, sig, run["invoice_ref"], "controller", lines)
    actions = [e["action"] for e in client.get("/audit", headers=h).json()["entries"]][-3:]
    assert actions == ["approval.approve", "workflow.post", "run.posted"]
    assert client.get("/audit/verify", headers=h).json()["intact"] is True
    assert decide(client, h, run, role="controller", decision="approve").status_code == 409  # not paused any more


def test_a_bank_change_needs_the_controller_and_the_phone_box(client, db):
    h, run = start(client, "08")
    assert run["pause"]["controller_only"] is True
    assert decide(client, h, run, role="controller", decision="approve", reason="looks fine").status_code == 400
    assert decide(client, h, run, role="clerk", decision="approve", reason="x", phone_confirmed=True).status_code == 403
    r = decide(client, h, run, role="controller", decision="approve", reason="called 4417 number on file; vendor confirmed the change", phone_confirmed=True)
    assert r.status_code == 200 and r.json()["status"] == "posted"
    assert posted(db, run["invoice_ref"]) == 1


def test_an_override_without_a_reason_gets_a_400(client, db):
    h, run = start(client, "03")  # PRICE_VARIANCE, clerk
    assert decide(client, h, run, role="clerk", decision="approve").status_code == 400
    assert posted(db, run["invoice_ref"]) == 0
    r = decide(client, h, run, role="clerk", decision="approve", reason="new price agreed with the vendor on 2026-11-06")
    assert r.status_code == 200 and r.json()["status"] == "posted"


def test_reject_posts_nothing_and_hold_keeps_the_run_waiting(client, db):
    h, run = start(client, "10")
    r = decide(client, h, run, role="clerk", decision="hold", reason="asked for an actual meter read")
    assert r.status_code == 200 and r.json()["paused"] is True
    r = decide(client, h, run, role="clerk", decision="reject", reason="estimated read; vendor will re-bill")
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["paused"] is False
    assert posted(db, run["invoice_ref"]) == 0


def test_an_invoice_with_no_entry_to_post_cannot_be_approved(client):
    h, run = start(client, "11")  # vendor not in the master: no account, no lines
    r = decide(client, h, run, role="controller", decision="approve", reason="x")
    assert r.status_code == 400 and "no entry" in r.json()["detail"]


def test_another_visitor_cannot_decide_on_a_run(client):
    h, run = start(client, "09")
    other = {"X-Session-Id": client.post("/sessions").json()["session_id"]}
    assert decide(client, other, run, role="controller", decision="approve").status_code == 404
