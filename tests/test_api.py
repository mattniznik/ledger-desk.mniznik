"""The app API, part 1: visitor sessions and the audit log (docs/decisions/0004).

Each visitor gets a session; the session id is a random UUID the browser keeps and sends in the
X-Session-Id header (a header, not the URL, so it stays out of access logs). Every request runs
as the ledger_app role with that session set for its transaction only, so Postgres row-level
security, not the API code, keeps one visitor's rows from another. The audit log is read and
verified through the API; an edited row is found.
"""

import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from ledger_desk.api import create_api, session_conn
from ledger_desk.company import build_company
from ledger_desk.db import connect, reset_database, seed_erp

API_DB = "ledger_desk_test_api"


@pytest.fixture(scope="module")
def api_db():
    reset_database(API_DB)
    with connect(API_DB) as conn:
        seed_erp(conn, build_company())
        conn.commit()
    return API_DB


@pytest.fixture
def client(api_db):
    return TestClient(create_api(api_db))


def new_session(client) -> str:
    r = client.post("/sessions")
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def test_a_new_session_starts_its_audit_log(client):
    sid = new_session(client)
    assert uuid.UUID(sid).version == 4
    rows = client.get("/audit", headers={"X-Session-Id": sid}).json()["entries"]
    assert [(r["actor"], r["action"]) for r in rows] == [("system", "session.created")]
    assert rows[0]["prev_hash"] == "genesis" and len(rows[0]["hash"]) == 64
    v = client.get("/audit/verify", headers={"X-Session-Id": sid}).json()
    assert v == {"intact": True, "rows": 1, "first_bad_id": None}


def test_one_visitor_never_sees_anothers_audit_rows(client):
    a, b = new_session(client), new_session(client)
    rows_a = client.get("/audit", headers={"X-Session-Id": a}).json()["entries"]
    rows_b = client.get("/audit", headers={"X-Session-Id": b}).json()["entries"]
    assert {r["session_id"] for r in rows_a} == {a} and {r["session_id"] for r in rows_b} == {b}


def test_no_session_is_401_and_an_unknown_one_is_404(client):
    assert client.get("/audit").status_code == 401
    assert client.get("/audit", headers={"X-Session-Id": str(uuid.uuid4())}).status_code == 404
    assert client.get("/audit", headers={"X-Session-Id": "not-a-uuid"}).status_code == 401


def test_verify_through_the_api_finds_a_row_edited_behind_its_back(client, api_db):
    sid = new_session(client)
    with session_conn(api_db, uuid.UUID(sid)) as conn:
        from ledger_desk.db import audit_append

        audit_append(conn, uuid.UUID(sid), "ai", "read", "GCI-2301", {"total": "6200.00"})
        audit_append(conn, uuid.UUID(sid), "code", "check", "GCI-2301", {"flags": []})
    # the table owner, not the app, edits the middle row
    with connect(api_db) as admin:
        target = admin.execute("SELECT id FROM app.audit_log WHERE session_id = %s AND action = 'read'", (sid,)).fetchone()[0]
        admin.execute("UPDATE app.audit_log SET detail = '{\"total\": \"62.00\"}' WHERE id = %s", (target,))
        admin.commit()
    v = client.get("/audit/verify", headers={"X-Session-Id": sid}).json()
    assert v == {"intact": False, "rows": 3, "first_bad_id": target}


def test_the_tamper_button_edits_one_of_this_visitors_rows_and_verify_finds_it(client):
    a, b = new_session(client), new_session(client)
    r = client.post("/audit/tamper", headers={"X-Session-Id": a})
    assert r.status_code == 200
    edited = r.json()["edited_id"]
    v = client.get("/audit/verify", headers={"X-Session-Id": a}).json()
    assert v["intact"] is False and v["first_bad_id"] == edited
    assert client.get("/audit/verify", headers={"X-Session-Id": b}).json()["intact"] is True  # nobody else's log


def test_the_api_runs_as_ledger_app_with_the_session_set_only_inside_its_transaction(api_db, client):
    sid = uuid.UUID(new_session(client))
    with session_conn(api_db, sid) as conn:
        assert conn.execute("SELECT current_user").fetchone()[0] == "ledger_app"
        assert conn.execute("SELECT app.current_session()").fetchone()[0] == sid
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():  # a savepoint, so the refusal does not abort the request's transaction
                conn.execute("UPDATE app.audit_log SET actor = 'x'")
