"""The local database: migrations, the ERP seed, and the audit-log calls.

Local development: Postgres in Docker on 127.0.0.1:55432 with trust auth (docker-compose.yml). A deployment
sets LEDGER_DESK_DB_URL, the server address with its password from Key Vault (docs/DEPLOY.md).

Migrations are plain SQL files run in name order, so the schema reads as SQL, not as an ORM's
idea of it. The audit hash chain is computed inside Postgres (app.audit_append), so no client can
write a row whose hash it chose itself without audit_verify noticing.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from urllib.parse import urlparse

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .company import Company

HOST = "127.0.0.1"
PORT = 55432
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

ERP_TABLES = ["accounts", "vendors", "purchase_orders", "po_lines", "receipts", "bills", "bill_lines"]


def url_for(dbname: str) -> str:
    """The database URL. Locally the Docker Postgres; in a container, LEDGER_DESK_DB_URL (server and
    login, no database name) set by the platform from its secret store, never baked into an image."""
    base = os.environ.get("LEDGER_DESK_DB_URL") or f"postgresql://postgres@{HOST}:{PORT}"
    return f"{base.rstrip('/')}/{dbname}"


def admin_url() -> str:
    """The maintenance database on the same server every other connection uses, for dropping and creating."""
    return url_for("postgres")


def connect(dbname: str) -> psycopg.Connection:
    return psycopg.connect(url_for(dbname))


# One pool per database and purpose, shared by every app in the process. Each request used to open its own
# connections: a page load of 13 bills opened dozens, the browser tests ran a Windows machine out of local ports
# ("Address already in use", 10048), and a small hosted Postgres caps how many connections it takes.
POOL_MAX = 10  # per pool: the API's two and the ERP's one make 30 of Azure B1ms's 35 user connections (docs/DEPLOY.md)
_POOLS: dict[tuple[str, str], ConnectionPool] = {}
_POOLS_LOCK = threading.Lock()


def pool(dbname: str, role: str) -> ConnectionPool:
    """A shared pool for a database. role "ledger_app" or "ledger_erp": each connection switches to that role once
    (row-level security still needs the visitor's session set per transaction, which the caller does). role
    "checkpoint": the autocommit, dict-row connections LangGraph's PostgresSaver makes in from_conn_string."""
    key = (url_for(dbname), role)
    with _POOLS_LOCK:
        p = _POOLS.get(key)
        if p is None:
            checkpoint = role == "checkpoint"

            def configure(conn: psycopg.Connection) -> None:
                if not checkpoint:
                    conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
                    conn.commit()

            kwargs = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row} if checkpoint else {}
            p = ConnectionPool(url_for(dbname), min_size=1, max_size=POOL_MAX, kwargs=kwargs, configure=configure,
                               check=ConnectionPool.check_connection, open=True)
            _POOLS[key] = p
        return p


def close_pools(dbname: str | None = None) -> None:
    """Close the pools for a database (all of them with no name), before it is dropped."""
    with _POOLS_LOCK:
        for key in [k for k in _POOLS if dbname is None or k[0] == url_for(dbname)]:
            _POOLS.pop(key).close()


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS public.schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    done = {r[0] for r in conn.execute("SELECT name FROM public.schema_migrations").fetchall()}
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        conn.execute(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO public.schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    conn.commit()
    return applied


def is_local(url: str) -> bool:
    """Whether a database URL points at this machine (a loopback address)."""
    return urlparse(url).hostname in {"127.0.0.1", "::1", "localhost"}


def reset_database(dbname: str) -> None:
    """Drop and recreate a database, then migrate it. For tests and local resets only: it refuses any server that is
    not on this machine, so LEDGER_DESK_DB_URL set for a deployment can never make it drop the deployed database."""
    if not is_local(admin_url()):
        raise RuntimeError(f"refusing to drop {dbname!r}: db-reset only works on a database on this machine (127.0.0.1, ::1 or localhost)")
    close_pools(dbname)  # pooled connections to it would be cut off by the drop
    with psycopg.connect(admin_url(), autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    with connect(dbname) as conn:
        apply_migrations(conn)


def seed_erp_if_empty(conn: psycopg.Connection, company: Company) -> bool:
    """Seed the demo company when the ERP has no vendors yet, and say whether it did. A deployed database is never
    reset (reset_database refuses it), so the API calls this on start; a seeded database is left alone."""
    if conn.execute("SELECT count(*) FROM erp.vendors").fetchone()[0]:
        return False
    seed_erp(conn, company)
    conn.commit()
    return True


def seed_erp(conn: psycopg.Connection, company: Company) -> None:
    for a in company.accounts:
        conn.execute("INSERT INTO erp.accounts (number, name) VALUES (%s, %s)", (a.number, a.name))
    for v in company.vendors:
        conn.execute(
            "INSERT INTO erp.vendors VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (v.id, v.name, v.tax_id, v.category, v.terms_days, v.default_account, v.bank.bank, v.bank.account_last4, v.uses_po, v.recurring),
        )
    for po in company.purchase_orders:
        conn.execute("INSERT INTO erp.purchase_orders VALUES (%s, %s, %s)", (po.number, po.vendor_id, po.date))
        for line in po.lines:
            conn.execute(
                "INSERT INTO erp.po_lines VALUES (%s, %s, %s, %s, %s, %s)",
                (po.number, line.line, line.description, line.quantity, line.unit_price, line.account),
            )
    for r in company.receipts:
        conn.execute("INSERT INTO erp.receipts (po, line, quantity, date) VALUES (%s, %s, %s, %s)", (r.po, r.line, r.quantity, r.date))
    for b in company.bills:
        bill_id = conn.execute(
            "INSERT INTO erp.bills (vendor_id, number, date, total, po, status) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (b.vendor_id, b.number, b.date, b.total, b.po, b.status),
        ).fetchone()[0]
        for bl in b.lines:
            conn.execute("INSERT INTO erp.bill_lines VALUES (%s, %s, %s)", (bill_id, bl.po_line, bl.quantity))


def erp_table_hashes(conn: psycopg.Connection) -> dict[str, str]:
    """md5 of every ERP table's rows in a fixed order: equal maps mean identical data."""
    out = {}
    for table in ERP_TABLES:
        query = sql.SQL("SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) FROM erp.{} t").format(sql.Identifier(table))
        out[table] = conn.execute(query).fetchone()[0]
    return out


def audit_append(conn: psycopg.Connection, session: uuid.UUID, actor: str, action: str, entity: str, detail: dict) -> int:
    return conn.execute(
        "SELECT app.audit_append(%s, %s, %s, %s, %s::jsonb)", (session, actor, action, entity, json.dumps(detail))
    ).fetchone()[0]


def audit_verify(conn: psycopg.Connection, session: uuid.UUID) -> int | None:
    """None when the session's audit log is intact, else the id of the first row that is not."""
    return conn.execute("SELECT app.audit_verify(%s)", (session,)).fetchone()[0]
