"""Shared fixtures for the ERP tests: a seeded database, an approval key pair, the app."""

import uuid
from pathlib import Path

import psycopg
import pytest

from ledger_desk.approval import new_key_pair
from ledger_desk.company import build_company
from ledger_desk.db import admin_url, connect, reset_database, seed_erp

ERP_TEST_DB = "ledger_desk_test_erp"
OUT = Path(__file__).resolve().parents[1] / "out"


@pytest.fixture(scope="session", autouse=True)
def rendered_documents():
    """Several tests read the samples' documents from out/, which is not published: render them first. A
    document already there with the same bytes is left alone (documents.render_case)."""
    from ledger_desk.documents import render_case
    from ledger_desk.invoices import load_all

    for case in load_all():
        render_case(case, OUT)


@pytest.fixture(scope="session")
def erp_db():
    try:
        reset_database(ERP_TEST_DB)
    except psycopg.OperationalError as e:
        pytest.fail(f"local Postgres is not reachable at {admin_url()} ({e}); run `docker compose up -d`")
    with connect(ERP_TEST_DB) as conn:
        seed_erp(conn, build_company())
        conn.commit()
    return ERP_TEST_DB


@pytest.fixture(scope="session")
def keys():
    return new_key_pair()


@pytest.fixture
def app(erp_db, keys):
    from ledger_desk.erp.app import create_app

    return create_app(erp_db, api_key="test-api-key", approval_public_key=keys.public)


@pytest.fixture
def ref():
    """A fresh invoice reference per test, so entry counts never mix between tests."""
    return f"TEST-{uuid.uuid4().hex[:10]}"


def entries_for(dbname: str, invoice_ref: str) -> int:
    with connect(dbname) as conn:
        return conn.execute("SELECT count(*) FROM erp.journal_entries WHERE invoice_ref = %s", (invoice_ref,)).fetchone()[0]
