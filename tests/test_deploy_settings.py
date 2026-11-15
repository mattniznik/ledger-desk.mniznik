"""Deploy settings: on Azure the API and the mock ERP are separate containers.

The API must then call the ERP over HTTP with the ERP's key, and both sides must share one
approval key pair: the API signs with the private half, the ERP verifies with the public half. In
one process (locally) all three are made up on the spot; across containers they come from the
environment, filled by the platform from its secret store. A half-configured deployment is refused
at start-up instead of failing on the first approval.
"""

import socket
import threading
import time
import uuid
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from ledger_desk.api import create_api
from ledger_desk.approval import new_key_pair, private_from_b64, private_to_b64, public_from_b64, public_to_b64, sign, verify
from ledger_desk.db import connect
from ledger_desk.erp.app import create_app as create_erp
from ledger_desk.settings import SettingsError, api_settings, erp_settings

REPLAYS = Path(__file__).resolve().parents[1] / "replays" / "claude-opus-5-5-low-run2"
LINES = [{"account": "6200", "debit": "10.00", "credit": "0.00"}, {"account": "2000", "debit": "0.00", "credit": "10.00"}]


def test_approval_keys_survive_a_trip_through_text():
    keys = new_key_pair()
    private, public = private_from_b64(private_to_b64(keys.private)), public_from_b64(public_to_b64(keys.public))
    assert verify(keys.public, sign(private, "r", "clerk", LINES), "r", "clerk", LINES)
    assert verify(public, sign(keys.private, "r", "clerk", LINES), "r", "clerk", LINES)


def test_with_nothing_set_the_api_runs_the_erp_in_process():
    s = api_settings({})
    assert (s.erp_url, s.erp_key, s.keys) == (None, None, None)


def test_a_separate_erp_needs_its_key_and_the_shared_approval_key():
    keys = new_key_pair()
    full = {"LEDGER_DESK_ERP_URL": "http://erp:8100", "LEDGER_DESK_ERP_KEY": "k", "LEDGER_DESK_APPROVAL_PRIVATE_KEY": private_to_b64(keys.private)}
    s = api_settings(full)
    assert s.erp_url == "http://erp:8100" and s.erp_key == "k" and public_to_b64(s.keys.public) == public_to_b64(keys.public)
    with pytest.raises(SettingsError, match="LEDGER_DESK_ERP_KEY"):
        api_settings({k: v for k, v in full.items() if k != "LEDGER_DESK_ERP_KEY"})
    with pytest.raises(SettingsError, match="LEDGER_DESK_APPROVAL_PRIVATE_KEY"):
        api_settings({k: v for k, v in full.items() if k != "LEDGER_DESK_APPROVAL_PRIVATE_KEY"})


def test_the_erp_takes_its_key_and_the_public_half_from_the_environment():
    keys = new_key_pair()
    key, public = erp_settings({"LEDGER_DESK_ERP_KEY": "k2", "LEDGER_DESK_APPROVAL_PUBLIC_KEY": public_to_b64(keys.public)})
    assert key == "k2" and public_to_b64(public) == public_to_b64(keys.public)
    local_key, local_public = erp_settings({})
    assert local_key == "local-dev-key" and local_public is not None  # local only: a throwaway pair


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def erp_over_http(erp_db):
    """The mock ERP as a real HTTP server in another thread, with its own key and a public key."""
    servers = []

    def start(public_key, api_key="erp-key", seen=None):
        port = free_port()
        app = create_erp(erp_db, api_key=api_key, approval_public_key=public_key)
        if seen is not None:  # what reached this server over the wire

            @app.middleware("http")
            async def record(request, call_next):
                seen.append((request.method, request.url.path))
                return await call_next(request)

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        servers.append(server)
        return f"http://127.0.0.1:{port}"

    yield start
    for s in servers:
        s.should_exit = True


def entries(db, ref):
    with connect(db) as conn:
        return conn.execute("SELECT count(*) FROM erp.journal_entries WHERE invoice_ref = %s", (ref,)).fetchone()[0]


def approve_13(client):
    h = {"X-Session-Id": client.post("/sessions").json()["session_id"]}
    run = client.post("/runs", json={"invoice": "13"}, headers=h).json()
    return run, h, client.post(f"/runs/{run['run_id']}/decision", json={"role": "controller", "decision": "approve"}, headers=h)


def test_an_approved_invoice_posts_to_a_separate_erp_over_http(erp_db, erp_over_http, tmp_path):
    keys = new_key_pair()
    seen: list = []
    url = erp_over_http(keys.public, seen=seen)
    client = TestClient(create_api(erp_db, docs_dir=tmp_path, replays_dir=REPLAYS, keys=keys, erp_url=url, erp_key="erp-key"))
    run, _, r = approve_13(client)
    assert r.status_code == 200 and r.json()["status"] == "posted", r.text
    assert entries(erp_db, run["invoice_ref"]) == 1
    assert seen.count(("POST", "/journal-entries")) == 1  # the posting went over HTTP to this server


def test_when_the_erp_refuses_the_signature_nothing_posts_and_the_audit_says_so(erp_db, erp_over_http, tmp_path):
    url = erp_over_http(new_key_pair().public)  # the ERP was given the wrong public half
    client = TestClient(create_api(erp_db, docs_dir=tmp_path, replays_dir=REPLAYS, keys=new_key_pair(), erp_url=url, erp_key="erp-key"))
    run, h, r = approve_13(client)
    assert r.status_code == 502 and "refused" in r.json()["detail"]
    assert entries(erp_db, run["invoice_ref"]) == 0
    last = client.get("/audit", headers=h).json()["entries"][-1]
    assert (last["actor"], last["action"]) == ("code", "workflow.post_failed")
    # the run says so too: the workflow's own state still reads "ready", and a screen that trusted it
    # showed "Approved and booked" for a bill that never posted (review, 2026-11-14)
    view = client.get(f"/runs/{run['run_id']}", headers=h).json()
    assert view["status"] == "post_failed" and view["entry_id"] is None


def test_a_run_is_committed_before_the_answer_reaches_the_client(erp_db, tmp_path, monkeypatch):
    # FastAPI ends a yield dependency after the response is sent unless its scope is "function"; the request's
    # transaction then committed after the client had its answer, so a client that acted at once could find
    # "no such run in this session" (measured in the API's image on Linux: 3 of 12 approvals, 2026-11-15). Each
    # commit is slowed here, so the old order fails every time instead of now and then.
    import psycopg

    original_exit = psycopg.Transaction.__exit__

    def slow_exit(self, *exc):
        time.sleep(0.3)
        return original_exit(self, *exc)

    monkeypatch.setattr(psycopg.Transaction, "__exit__", slow_exit)
    port = free_port()
    api = create_api(erp_db, docs_dir=tmp_path, replays_dir=REPLAYS)
    server = uvicorn.Server(uvicorn.Config(api, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    try:
        import httpx

        c = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30)
        h = {"X-Session-Id": c.post("/sessions").json()["session_id"]}
        run = c.post("/runs", json={"invoice": "09"}, headers=h).json()
        r = c.post(f"/runs/{run['run_id']}/decision", json={"role": "clerk", "decision": "approve"}, headers=h)
        assert r.status_code == 200, r.text
    finally:
        server.should_exit = True
