"""The mock ERP: a separate service with its own tables, its own database role and its own API key.
The shapes are generic, not a copy of any real product's API.

    uv run ledger-desk erp-serve      then open http://127.0.0.1:8100/docs

Posting is the one write, and it is guarded three ways:
- an Idempotency-Key header: the same key and body returns the first entry, so a retry after a lost
  response can never post twice; the same key with a different body is a 409;
- an approval signature (Ed25519) over exactly what is being posted, verified with the public key;
- a balance check here (422) with the database's deferred trigger behind it.

"Break the ERP" switches (POST /admin/switches) make the next N posts return 429 with Retry-After,
fail with 503 before writing, or commit and then fail with 503 as if the response were lost. They
exist so the demo and the tests can show the client's retries producing exactly one entry.

Money leaves as strings: FastAPI would otherwise encode Decimal as a float.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal

import psycopg
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..approval import verify
from ..db import pool, url_for


class LineIn(BaseModel):
    account: str
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)


class ApprovalIn(BaseModel):
    approver: str
    signature: str


class EntryIn(BaseModel):
    invoice_ref: str
    lines: list[LineIn]
    approval: ApprovalIn | None = None


class Switches(BaseModel):
    rate_limit: int = 0
    retry_after: int = 1
    fail_before: int = 0
    fail_after_commit: int = 0


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _row(cursor, row) -> dict:
    return {d.name: _plain(v) for d, v in zip(cursor.description, row)}


def _rows(cursor) -> list[dict]:
    return [_row(cursor, r) for r in cursor.fetchall()]


def _request_hash(body: EntryIn) -> str:
    doc = {
        "invoice_ref": body.invoice_ref,
        "lines": [[l.account, f"{l.debit:.2f}", f"{l.credit:.2f}"] for l in body.lines],
        "approval": [body.approval.approver, body.approval.signature] if body.approval else None,
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def create_app(dbname: str, api_key: str, approval_public_key: Ed25519PublicKey) -> FastAPI:
    app = FastAPI(title="Mock ERP (fictional)", description="The coffee roastery's mock ERP for the ledger-desk demo.")
    app.state.switches = Switches()

    def require_key(x_api_key: str | None = Header(default=None)):
        if not x_api_key or not hmac.compare_digest(x_api_key, api_key):
            raise HTTPException(401, "missing or wrong API key")

    def db():
        # a pooled connection that is already ledger_erp (db.pool); returned to the pool after the request, rolled
        # back if the endpoint left a transaction open, as closing it did before
        with pool(dbname, "ledger_erp").connection() as conn:
            yield conn

    auth = [Depends(require_key)]

    @app.get("/accounts", dependencies=auth)
    def accounts(conn=Depends(db, scope="function")):
        return _rows(conn.execute("SELECT number, name FROM erp.accounts ORDER BY number"))

    @app.get("/vendors", dependencies=auth)
    def vendors(name: str | None = None, tax_id: str | None = None, conn=Depends(db, scope="function")):
        cur = conn.execute(
            "SELECT * FROM erp.vendors WHERE (%(n)s::text IS NULL OR lower(name) = lower(%(n)s)) AND (%(t)s::text IS NULL OR tax_id = %(t)s) ORDER BY id",
            {"n": name, "t": tax_id},
        )
        return _rows(cur)

    @app.get("/vendors/{vendor_id}", dependencies=auth)
    def vendor(vendor_id: str, conn=Depends(db, scope="function")):
        cur = conn.execute("SELECT * FROM erp.vendors WHERE id = %s", (vendor_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, f"no vendor {vendor_id}")
        return _row(cur, row)

    @app.get("/purchase-orders/{po}", dependencies=auth)
    def purchase_order(po: str, conn=Depends(db, scope="function")):
        cur = conn.execute("SELECT number, vendor_id, date FROM erp.purchase_orders WHERE number = %s", (po,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, f"no purchase order {po}")
        out = _row(cur, row)
        out["lines"] = _rows(conn.execute("SELECT line, description, quantity, unit_price, account FROM erp.po_lines WHERE po = %s ORDER BY line", (po,)))
        return out

    @app.get("/purchase-orders/{po}/receipts", dependencies=auth)
    def receipts(po: str, conn=Depends(db, scope="function")):
        return _rows(conn.execute("SELECT line, quantity, date FROM erp.receipts WHERE po = %s ORDER BY id", (po,)))

    @app.get("/bills", dependencies=auth)
    def bills(
        vendor_id: str | None = None,
        number: str | None = None,
        date_from: date | None = Query(default=None, alias="from"),
        date_to: date | None = Query(default=None, alias="to"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        conn=Depends(db, scope="function"),
    ):
        cur = conn.execute(
            """SELECT id, vendor_id, number, date, total, po, status FROM erp.bills
               WHERE (%(v)s::text IS NULL OR vendor_id = %(v)s) AND (%(n)s::text IS NULL OR number = %(n)s)
                 AND (%(f)s::date IS NULL OR date >= %(f)s) AND (%(t)s::date IS NULL OR date <= %(t)s)
               ORDER BY date, id LIMIT %(l)s OFFSET %(o)s""",
            {"v": vendor_id, "n": number, "f": date_from, "t": date_to, "l": limit + 1, "o": offset},
        )
        items = _rows(cur)
        more = len(items) > limit
        return {"items": items[:limit], "next_offset": offset + limit if more else None}

    @app.get("/journal-entries/{entry_id}", dependencies=auth)
    def journal_entry(entry_id: int, conn=Depends(db, scope="function")):
        cur = conn.execute("SELECT id, invoice_ref, approver, posted_at FROM erp.journal_entries WHERE id = %s", (entry_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, f"no journal entry {entry_id}")
        out = _row(cur, row)
        out["posted_at"] = str(out["posted_at"])
        out["lines"] = _rows(conn.execute("SELECT account, debit, credit FROM erp.journal_lines WHERE entry_id = %s ORDER BY id", (entry_id,)))
        return out

    @app.post("/admin/switches", dependencies=auth)
    def set_switches(switches: Switches):
        app.state.switches = switches
        return switches

    @app.post("/journal-entries", dependencies=auth)
    def post_entry(body: EntryIn, idempotency_key: str | None = Header(default=None), conn=Depends(db, scope="function")):
        if not idempotency_key:
            return JSONResponse({"detail": "an Idempotency-Key header is required"}, 400)

        s = app.state.switches
        if s.rate_limit > 0:
            s.rate_limit -= 1
            return JSONResponse({"detail": "rate limited"}, 429, headers={"Retry-After": str(s.retry_after)})
        if s.fail_before > 0:
            s.fail_before -= 1
            return JSONResponse({"detail": "ERP unavailable"}, 503)

        request_hash = _request_hash(body)
        existing = conn.execute("SELECT id, request_hash FROM erp.journal_entries WHERE idempotency_key = %s", (idempotency_key,)).fetchone()
        if existing:
            if existing[1] != request_hash:
                return JSONResponse({"detail": "this Idempotency-Key was used for a different entry"}, 409)
            return JSONResponse({"id": existing[0], "replayed": True}, 200)

        lines = [l.model_dump() for l in body.lines]
        if body.approval is None or not verify(approval_public_key, body.approval.signature, body.invoice_ref, body.approval.approver, lines):
            return JSONResponse({"detail": "a valid approval signature for exactly this entry is required"}, 403)

        debits = sum((l.debit for l in body.lines), Decimal(0))
        credits = sum((l.credit for l in body.lines), Decimal(0))
        one_sided = all((l.debit == 0) != (l.credit == 0) and l.debit >= 0 and l.credit >= 0 for l in body.lines)
        if len(body.lines) < 2 or debits != credits or not one_sided:
            return JSONResponse({"detail": f"the entry does not balance: debits {debits}, credits {credits}"}, 422)

        try:
            entry_id = conn.execute(
                "INSERT INTO erp.journal_entries (invoice_ref, idempotency_key, request_hash, approver, signature) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (body.invoice_ref, idempotency_key, request_hash, body.approval.approver, body.approval.signature),
            ).fetchone()[0]
            for l in body.lines:
                conn.execute("INSERT INTO erp.journal_lines (entry_id, account, debit, credit) VALUES (%s, %s, %s, %s)", (entry_id, l.account, l.debit, l.credit))
            conn.commit()
        except psycopg.errors.UniqueViolation:
            # Two requests with the same key raced; the other one won. Answer like a replay.
            conn.rollback()
            row = conn.execute("SELECT id, request_hash FROM erp.journal_entries WHERE idempotency_key = %s", (idempotency_key,)).fetchone()
            if row[1] != request_hash:
                return JSONResponse({"detail": "this Idempotency-Key was used for a different entry"}, 409)
            return JSONResponse({"id": row[0], "replayed": True}, 200)
        except (psycopg.errors.ForeignKeyViolation, psycopg.errors.RaiseException, psycopg.errors.CheckViolation) as e:
            conn.rollback()
            return JSONResponse({"detail": f"rejected by the ledger: {e.diag.message_primary}"}, 422)

        if s.fail_after_commit > 0:
            s.fail_after_commit -= 1
            return JSONResponse({"detail": "ERP unavailable (the entry was written; the response was lost)"}, 503)
        return JSONResponse({"id": entry_id, "replayed": False}, 201)

    return app
