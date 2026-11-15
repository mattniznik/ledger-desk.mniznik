"""The app API, part 2: runs. A visitor starts a run on a sample invoice; it goes through the real
workflow to the approval pause and every step lands in the session's audit log.

Runs replay a recorded real run by default (run 2, Claude Opus 5.5, 13 of 13): the recorded
replies go back through today's code, so the demo shows real model output for $0. Scripted (no
model, from the ground truth) is the fallback. The pause is kept by LangGraph's Postgres
checkpointer, so a run survives a restart of the API.
"""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ledger_desk.api import create_api
from ledger_desk.company import build_company
from ledger_desk.db import connect, reset_database, seed_erp

RUNS_DB = "ledger_desk_test_api_runs"
ROOT = Path(__file__).resolve().parents[1]
REPLAYS = ROOT / "replays" / "claude-opus-5-5-low-run2"


@pytest.fixture(scope="module")
def runs_db():
    reset_database(RUNS_DB)
    with connect(RUNS_DB) as conn:
        seed_erp(conn, build_company())
        conn.commit()
    return RUNS_DB


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    return tmp_path_factory.mktemp("api-docs")


@pytest.fixture
def client(runs_db, docs):
    return TestClient(create_api(runs_db, docs_dir=docs, replays_dir=REPLAYS))


def session(client) -> dict:
    return {"X-Session-Id": client.post("/sessions").json()["session_id"]}


def test_a_replayed_run_pauses_for_approval_with_the_recorded_findings(client):
    h = session(client)
    r = client.post("/runs", json={"invoice": "08"}, headers=h)
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["mode"] == "replay" and run["model"] == "claude-opus-5-5"
    assert run["status"] == "exception" and run["paused"] is True
    pause = run["pause"]
    assert [f["code"] for f in pause["flags"]] == ["BANK_CHANGED"] and pause["approver"] == "controller"
    assert pause["account_suggestion"]["account"] == "6300" and "9921" in pause["explanation"]


def test_every_step_lands_in_the_audit_log_in_order(client):
    h = session(client)
    client.post("/runs", json={"invoice": "08"}, headers=h)
    entries = client.get("/audit", headers=h).json()["entries"]
    steps = [(e["actor"], e["action"]) for e in entries]
    assert steps == [
        ("system", "session.created"),
        ("person", "run.started"),
        ("ai", "workflow.read"),
        ("code", "workflow.check"),
        ("ai", "workflow.suggest_account"),
        ("ai", "workflow.investigate"),
        ("code", "workflow.propose"),
        ("workflow", "run.paused"),
    ]
    read = next(e for e in entries if e["action"] == "workflow.read")
    assert read["detail"]["model"] == "claude-opus-5-5" and read["detail"]["output_tokens"] > 0
    check = next(e for e in entries if e["action"] == "workflow.check")
    assert check["detail"]["flags"] == ["BANK_CHANGED"]
    assert client.get("/audit/verify", headers=h).json()["intact"] is True


def test_a_clean_invoice_has_no_investigation_step(client):
    h = session(client)
    client.post("/runs", json={"invoice": "09"}, headers=h)
    actions = [e["action"] for e in client.get("/audit", headers=h).json()["entries"]]
    assert "workflow.investigate" not in actions and actions[-1] == "run.paused"


def test_the_invoice_and_its_checks_are_stored_for_the_session(client):
    h = session(client)
    run = client.post("/runs", json={"invoice": "08"}, headers=h).json()
    invoices = client.get("/invoices", headers=h).json()["invoices"]
    assert len(invoices) == 1
    inv = invoices[0]
    assert (inv["number"], inv["vendor_name"], inv["status"], inv["total"], inv["run_id"]) == ("REP-3307", "Espresso Repair Service", "exception", "860.00", run["run_id"])
    assert inv["flags"] == ["BANK_CHANGED"]


def test_run_status_survives_a_restart_of_the_api(client, runs_db, docs):
    h = session(client)
    run = client.post("/runs", json={"invoice": "13"}, headers=h).json()
    fresh = TestClient(create_api(runs_db, docs_dir=docs, replays_dir=REPLAYS))  # a new app, new connections
    again = fresh.get(f"/runs/{run['run_id']}", headers=h).json()
    assert again["paused"] is True and again["status"] == "ready" and again["pause"]["approver"] == "controller"


def test_another_visitor_cannot_see_a_run(client):
    a, b = session(client), session(client)
    run = client.post("/runs", json={"invoice": "09"}, headers=a).json()
    assert client.get(f"/runs/{run['run_id']}", headers=b).status_code == 404
    assert client.get("/invoices", headers=b).json()["invoices"] == []


def test_a_recording_that_no_longer_matches_fails_the_run_and_says_so_in_the_audit(runs_db, docs, tmp_path):
    import json

    record = json.loads((REPLAYS / "09.json").read_text(encoding="utf-8"))
    record["replies"] = record["replies"][:1]  # read only, as if recorded before account suggestions
    (tmp_path / "09.json").write_text(json.dumps(record), encoding="utf-8")
    client = TestClient(create_api(runs_db, docs_dir=docs, replays_dir=tmp_path))
    h = session(client)
    r = client.post("/runs", json={"invoice": "09"}, headers=h)
    assert r.status_code == 409 and "no longer matches" in r.json()["detail"]
    last = client.get("/audit", headers=h).json()["entries"][-1]
    assert (last["actor"], last["action"]) == ("workflow", "run.failed")  # the row survived the failed request


def test_the_samples_list_offers_all_13_with_what_each_shows(client):
    samples = client.get("/samples").json()["samples"]
    assert [s["id"] for s in samples] == [f"{i:02d}" for i in range(1, 14)]
    s08 = samples[7]
    assert (s08["vendor_name"], s08["number"], s08["total"], s08["document"]) == ("Espresso Repair Service", "REP-3307", "860.00", "pdf")
    assert "remit-to account differs" in s08["what_is_wrong"] and samples[1]["document"] == "photo"
    assert all(s["replay"] for s in samples)  # every sample has a recorded real run to replay


def test_api_serve_dry_run_migrates_and_lists_the_routes(runs_db, capsys):
    from ledger_desk.cli import main

    assert main(["api-serve", "--db", runs_db, "--dry-run"]) == 0
    out = capsys.readouterr().out
    for route in ("POST /sessions", "GET /samples", "POST /runs", "POST /runs/{run_id}/decision", "GET /audit/verify"):
        assert route in out


def test_a_run_shows_what_was_read_and_its_document_only_to_its_session(client):
    h = session(client)
    run = client.post("/runs", json={"invoice": "08"}, headers=h).json()
    assert run["extraction"]["number"] == "REP-3307" and run["source_checks"]["total"] == "ok"
    assert run["email_draft"]["subject"]  # the agent's draft, shown for the clerk to send or not
    doc = client.get(f"/runs/{run['run_id']}/document", headers=h)
    assert doc.status_code == 200 and doc.headers["content-type"] == "application/pdf" and doc.content.startswith(b"%PDF")
    photo_run = client.post("/runs", json={"invoice": "02"}, headers=h).json()
    photo = client.get(f"/runs/{photo_run['run_id']}/document", headers=h)
    assert photo.headers["content-type"] == "image/jpeg" and photo.content[:2] == b"\xff\xd8"
    assert photo_run["source_checks"]["total"] == "not_checked"  # a photo has no text layer
    other = session(client)
    assert client.get(f"/runs/{run['run_id']}/document", headers=other).status_code == 404


def test_a_replayed_run_reports_how_long_the_recorded_run_took(client):
    import json

    h = session(client)
    run = client.post("/runs", json={"invoice": "08"}, headers=h).json()
    recorded = json.loads((REPLAYS / "08.json").read_text(encoding="utf-8"))["seconds"]
    assert run["seconds"] == recorded and run["metrics"]["model_calls"] >= 3
    assert client.post("/runs", json={"invoice": "09", "mode": "scripted"}, headers=h).json()["seconds"] is None


def test_scripted_mode_and_unknown_invoices(client):
    h = session(client)
    r = client.post("/runs", json={"invoice": "09", "mode": "scripted"}, headers=h).json()
    assert r["mode"] == "scripted" and r["status"] == "ready" and r["paused"] is True
    assert client.post("/runs", json={"invoice": "99"}, headers=h).status_code == 404
    assert client.post("/runs", json={"invoice": "09", "mode": "live"}, headers=h).status_code == 422


def test_a_run_says_when_the_bill_is_due_from_the_vendors_terms(client):
    from datetime import date, timedelta

    h = session(client)
    run = client.post("/runs", json={"invoice": "01"}, headers=h).json()
    vendor = build_company().vendor_by_name("Green Coffee Importer")
    assert vendor is not None and vendor.terms_days == 30  # Net 30, from the vendor master
    expected = (date.fromisoformat(run["extraction"]["date"]) + timedelta(days=30)).isoformat()
    assert run["due_date"] == expected
    credit = client.post("/runs", json={"invoice": "05"}, headers=h).json()
    assert credit["due_date"] is None  # a credit memo is not paid, it reduces what is owed
    unknown = client.post("/runs", json={"invoice": "11"}, headers=h).json()
    assert unknown["due_date"] is None  # no vendor record, so no terms


def test_a_decided_run_keeps_what_the_checks_found(client):
    h = session(client)
    run = client.post("/runs", json={"invoice": "07"}, headers=h).json()
    r = client.post(f"/runs/{run['run_id']}/decision", json={"role": "clerk", "decision": "reject"}, headers=h)
    assert r.status_code == 200, r.text
    view = client.get(f"/runs/{run['run_id']}", headers=h).json()
    assert view["status"] == "rejected" and view["pause"] is None
    assert [f["code"] for f in view["flags"]] == ["DUPLICATE"]  # what was caught stays caught after the decision


def test_reading_the_same_sample_twice_in_a_session_returns_the_first_run(client):
    h = session(client)
    first = client.post("/runs", json={"invoice": "08"}, headers=h)
    again = client.post("/runs", json={"invoice": "08"}, headers=h)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["run_id"] == first.json()["run_id"]
    assert [i["number"] for i in client.get("/invoices", headers=h).json()["invoices"]] == ["REP-3307"]


def test_two_reads_of_one_sample_at_the_same_moment_make_one_invoice(client):
    import threading

    h = session(client)
    gate = threading.Barrier(2)
    codes: list[int] = []

    def read():
        gate.wait()
        codes.append(client.post("/runs", json={"invoice": "09"}, headers=h).status_code)

    threads = [threading.Thread(target=read) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200, 201]
    assert len(client.get("/invoices", headers=h).json()["invoices"]) == 1


def test_a_problem_bill_comes_with_the_suggested_next_step_and_a_clean_one_without(client):
    h = session(client)
    dup = client.post("/runs", json={"invoice": "07"}, headers=h).json()
    step = dup["next_step"]
    assert (step["code"], step["decision"]) == ("DUPLICATE", "reject")
    assert step["reason"] == "Duplicate: DAI-5521 (dated Oct 14, 2026) already paid"  # corrected after review: the bill's date, not a payment date
    clean = client.post("/runs", json={"invoice": "09"}, headers=h).json()
    assert clean["paused"] is True and clean["next_step"] is None


def test_the_suggested_step_goes_through_the_decision_rules_and_a_held_bill_says_so(client):
    h = session(client)
    run = client.post("/runs", json={"invoice": "08"}, headers=h).json()
    assert run["held"] is False
    step = run["next_step"]
    r = client.post(f"/runs/{run['run_id']}/decision", json={"role": "clerk", "decision": step["decision"], "reason": step["reason"]}, headers=h)
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["held"] is True and view["paused"] is True  # still waiting for the phone call
    audit = client.get("/audit", headers=h).json()["entries"]
    held = [e for e in audit if e["action"] == "approval.hold"]
    assert held and held[-1]["detail"]["reason"] == step["reason"]


def test_an_overcharge_with_its_credit_memo_in_the_queue_is_approved_against_it(client):
    h = session(client)
    bill = client.post("/runs", json={"invoice": "03"}, headers=h).json()
    assert bill["next_step"]["decision"] == "hold"  # the credit has not been read yet
    client.post("/runs", json={"invoice": "05"}, headers=h)
    step = client.get(f"/runs/{bill['run_id']}", headers=h).json()["next_step"]
    assert step["decision"] == "approve" and "CM-PKG-0412" in step["reason"]
    r = client.post(f"/runs/{bill['run_id']}/decision", json={"role": "clerk", "decision": "approve", "reason": step["reason"]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "posted"


def test_a_rejected_credit_memo_does_not_settle_the_overcharge(client):
    h = session(client)
    bill = client.post("/runs", json={"invoice": "03"}, headers=h).json()
    credit = client.post("/runs", json={"invoice": "05"}, headers=h).json()
    client.post(f"/runs/{credit['run_id']}/decision", json={"role": "clerk", "decision": "reject"}, headers=h)
    assert client.get(f"/runs/{bill['run_id']}", headers=h).json()["next_step"]["decision"] == "hold"


def test_a_run_shows_the_agents_lookups_with_their_inputs_and_results(client):
    h = session(client)
    run = client.post("/runs", json={"invoice": "03"}, headers=h).json()
    lookups = run["lookups"]
    assert [l["tool"] for l in lookups] == ["get_purchase_order", "get_receipts", "get_vendor", "draft_vendor_email"]
    assert lookups[0]["input"] == {"po": "PO-1124"} and lookups[0]["result"] == "PO-1124: 1 line, 5,000 Hot cup, 12 oz at $0.38"
    assert lookups[1]["result"] == "1 delivery: 5,000 received"
    clean = client.post("/runs", json={"invoice": "09"}, headers=h).json()
    assert clean["lookups"] == []


def test_requests_reuse_pooled_connections_instead_of_opening_new_ones(client, monkeypatch):
    # Every request used to open its own connections (the session's, and the checkpointer's), so a page load of
    # 13 bills opened dozens; the browser tests ran a Windows machine out of local ports ("Address already in
    # use", 10048), and a small hosted database caps its connections.
    import psycopg

    h = session(client)
    run = client.post("/runs", json={"invoice": "09"}, headers=h).json()
    client.get(f"/runs/{run['run_id']}", headers=h)  # the pools have their connections now
    opened = []
    original_class, original_module = psycopg.Connection.connect, psycopg.connect

    def counting_class(cls, *a, **kw):
        opened.append("Connection.connect")
        return original_class(*a, **kw)

    def counting_module(*a, **kw):
        opened.append("psycopg.connect")
        return original_module(*a, **kw)

    monkeypatch.setattr(psycopg.Connection, "connect", classmethod(counting_class))
    monkeypatch.setattr(psycopg, "connect", counting_module)
    for _ in range(10):
        assert client.get(f"/runs/{run['run_id']}", headers=h).status_code == 200
    assert opened == []
