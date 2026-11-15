"""The guarantees the database itself enforces (docs/decisions/0004), on a real Postgres.

The prompt does not enforce "a person approves each posting"; these do. Each test runs as the
role that would really make the call (SET ROLE), never as the superuser, except where the point
is that even the table owner editing a row behind the app's back gets caught.

Needs the local database: `docker compose up -d`.
"""

import uuid

import psycopg
import pytest

from ledger_desk.company import build_company
from ledger_desk.db import admin_url, audit_append, audit_verify, connect, erp_table_hashes, reset_database, seed_erp

TEST_DB = "ledger_desk_test"


@pytest.fixture(scope="module")
def db():
    try:
        reset_database(TEST_DB)
    except psycopg.OperationalError as e:
        pytest.fail(f"local Postgres is not reachable at {admin_url()} ({e}); run `docker compose up -d`")
    with connect(TEST_DB) as conn:
        seed_erp(conn, build_company())
        conn.commit()
        yield conn


def as_role(conn, role, session=None):
    conn.execute(f"SET ROLE {role}")
    if session:
        conn.execute("SELECT set_config('app.session_id', %s, false)", (str(session),))


def reset_role(conn):
    conn.rollback()
    conn.execute("RESET ROLE")
    conn.execute("RESET app.session_id")
    conn.commit()


def test_seeding_twice_gives_identical_rows():
    reset_database(TEST_DB + "_a")
    reset_database(TEST_DB + "_b")
    hashes = []
    for name in (TEST_DB + "_a", TEST_DB + "_b"):
        with connect(name) as conn:
            seed_erp(conn, build_company())
            conn.commit()
            hashes.append(erp_table_hashes(conn))
    assert hashes[0] == hashes[1]
    assert set(hashes[0]) >= {"vendors", "purchase_orders", "po_lines", "receipts", "bills"}


def _post_entry(conn, lines):
    entry = conn.execute("INSERT INTO erp.journal_entries (invoice_ref, idempotency_key) VALUES (%s, %s) RETURNING id", ("PKG-20817", str(uuid.uuid4()))).fetchone()[0]
    for account, debit, credit in lines:
        conn.execute("INSERT INTO erp.journal_lines (entry_id, account, debit, credit) VALUES (%s, %s, %s, %s)", (entry, account, debit, credit))
    return entry


def test_an_unbalanced_journal_entry_is_rejected_at_commit(db):
    as_role(db, "ledger_erp")
    _post_entry(db, [("1210", "2100.00", "0"), ("2000", "0", "1900.00")])
    with pytest.raises(psycopg.errors.RaiseException, match="does not balance"):
        db.commit()
    reset_role(db)


def test_a_balanced_journal_entry_commits(db):
    as_role(db, "ledger_erp")
    entry = _post_entry(db, [("1210", "2100.00", "0"), ("2000", "0", "2100.00")])
    db.commit()
    assert db.execute("SELECT count(*) FROM erp.journal_lines WHERE entry_id = %s", (entry,)).fetchone()[0] == 2
    reset_role(db)


def test_the_audit_log_cannot_be_updated_or_deleted(db):
    session = uuid.uuid4()
    as_role(db, "ledger_app", session)
    db.execute("INSERT INTO app.sessions (id) VALUES (%s)", (session,))
    row = audit_append(db, session, "clerk", "approve", "invoice:3", {"reason": "price confirmed by phone"})
    db.commit()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("UPDATE app.audit_log SET actor = 'someone else' WHERE id = %s", (row,))
    db.rollback()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM app.audit_log WHERE id = %s", (row,))
    reset_role(db)


def test_verify_finds_a_row_edited_behind_the_apps_back(db):
    session = uuid.uuid4()
    as_role(db, "ledger_app", session)
    db.execute("INSERT INTO app.sessions (id) VALUES (%s)", (session,))
    ids = [audit_append(db, session, "system", "check", f"invoice:{n}", {"flags": n}) for n in range(1, 4)]
    db.commit()
    assert audit_verify(db, session) is None
    reset_role(db)
    # The table owner can still edit a row; the hash chain is what makes that visible.
    db.execute("UPDATE app.audit_log SET detail = '{\"flags\": 0}' WHERE id = %s", (ids[1],))
    db.commit()
    as_role(db, "ledger_app", session)
    assert audit_verify(db, session) == ids[1]
    reset_role(db)


def test_one_session_cannot_read_or_write_anothers_invoices(db):
    a, b = uuid.uuid4(), uuid.uuid4()
    for s in (a, b):
        as_role(db, "ledger_app", s)
        db.execute("INSERT INTO app.sessions (id) VALUES (%s)", (s,))
        db.execute("INSERT INTO app.invoices (session_id, vendor_name, number, status, total) VALUES (%s, 'Packaging Supplier', %s, 'received', 2100)", (s, f"PKG-{s.hex[:6]}"))
        db.commit()
        reset_role(db)
    as_role(db, "ledger_app", a)
    numbers = [r[0] for r in db.execute("SELECT number FROM app.invoices").fetchall()]
    assert numbers == [f"PKG-{a.hex[:6]}"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("INSERT INTO app.invoices (session_id, vendor_name, number, status, total) VALUES (%s, 'x', 'y', 'received', 1)", (b,))
    reset_role(db)


def test_the_agent_role_cannot_insert_an_approval(db):
    session = uuid.uuid4()
    as_role(db, "ledger_app", session)
    db.execute("INSERT INTO app.sessions (id) VALUES (%s)", (session,))
    invoice = db.execute("INSERT INTO app.invoices (session_id, vendor_name, number, status, total) VALUES (%s, 'Dairy Supplier', 'DAI-6120', 'exception', 504) RETURNING id", (session,)).fetchone()[0]
    db.commit()
    reset_role(db)
    as_role(db, "ledger_agent", session)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("INSERT INTO app.approvals (session_id, invoice_id, role, decision) VALUES (%s, %s, 'clerk', 'approve')", (session, invoice))
    reset_role(db)


def test_a_fresh_database_is_seeded_once_and_a_seeded_one_is_left_alone():
    # A deployed database is never reset (reset_database refuses any server not on this machine), so the API seeds
    # the demo company on start when the ERP is empty, and never touches it again.
    from ledger_desk.db import seed_erp_if_empty

    name = "ledger_desk_test_seed_once"
    reset_database(name)
    with connect(name) as conn:
        assert seed_erp_if_empty(conn, build_company()) is True
        vendors = conn.execute("SELECT count(*) FROM erp.vendors").fetchone()[0]
        assert vendors > 0
        assert seed_erp_if_empty(conn, build_company()) is False
        assert conn.execute("SELECT count(*) FROM erp.vendors").fetchone()[0] == vendors


def test_api_serve_seeds_a_fresh_database_on_start(capsys):
    from ledger_desk.cli import main

    name = "ledger_desk_test_serve_seeds"
    reset_database(name)  # migrated, nothing seeded: what a new deployed database looks like after migrations
    assert main(["api-serve", "--db", name, "--dry-run"]) == 0
    with connect(name) as conn:
        assert conn.execute("SELECT count(*) FROM erp.vendors").fetchone()[0] > 0
    assert "seeded the demo company" in capsys.readouterr().out


def test_the_login_that_runs_the_migrations_may_switch_to_each_app_role():
    # Postgres 16 and later give a non-superuser that creates a role only admin rights over it, not the right to SET
    # ROLE to it (measured in a fresh Postgres 17 as a CREATEROLE admin, as on Azure Flexible Server: "permission
    # denied to set role ledger_app"). The tests run as a superuser and never saw it, so check the grant itself.
    name = "ledger_desk_test_role_grants"
    reset_database(name)
    with connect(name) as conn:
        rows = conn.execute(
            """SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid JOIN pg_roles u ON u.oid = m.member
               WHERE u.rolname = current_user AND m.set_option ORDER BY r.rolname"""
        ).fetchall()
    assert [r[0] for r in rows] == ["ledger_agent", "ledger_app", "ledger_erp"]
