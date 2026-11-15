"""The app API: visitor sessions, runs, and the audit log.

Each visitor gets a session: a random UUID the browser keeps and sends in the `X-Session-Id`
header (a header rather than the URL, so it stays out of access logs). It works as a bearer
secret for a demo company copy, nothing more; there are no accounts.

Every request runs as the `ledger_app` role with `app.session_id` set for its own transaction
only (`set_config(..., true)`), so Postgres row-level security, not this code, decides which rows
a visitor can see or write. The superuser would bypass row-level security, which is why the role
is switched before anything else runs.

    POST /sessions          a new session; its audit log starts with session.created
    POST /runs              run a sample invoice through the workflow to the approval pause
    GET  /runs/{id}         a run's status and its pause, from the Postgres checkpointer
    GET  /invoices          this session's invoices with their flags
    GET  /audit             this session's audit log, oldest first
    GET  /audit/verify      walks the hash chain; the first row that does not check out, if any

Runs replay a recorded real run by default: the recorded model replies go back through today's
code (reading checks, rules, workflow), so a visitor sees real Claude output for $0. "scripted"
runs with no model at all. Each workflow step is written to the audit log as it happens, from
LangGraph's `stream_mode="updates"` (one chunk per node, then `__interrupt__` at the pause;
measured on langgraph 1.2.22, 2026-11-14). The run row says which session owns the run, under
row-level security; the run's own state is in LangGraph's checkpoint tables, keyed
"<session>:<run>", and is read only after that ownership check.
"""

from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Literal

import httpx
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from pydantic import BaseModel

from langgraph.types import Command

from .approval import KeyPair, new_key_pair, sign
from .authority import check_decision
from .company import build_company
from .db import audit_append, audit_verify, pool, url_for
from .documents import render_case
from .erp.app import create_app as create_erp
from .erp.client import ApprovalRejected, EntryConflict, EntryRejected, ErpClient, ErpUnavailable
from .invoices import load_all, load_case
from .playbook import next_step
from .runner import ReplayMismatch, ReplayModel, ScriptedReader
from .workflow import Deps, bill_due_date, build_workflow

ROOT = Path(__file__).resolve().parents[2]
ERP_KEY = "in-process"  # the ERP runs in-process locally; not a secret
RESULT_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,80}")  # a results file stem; no slashes, no dots at the start
STEP_ACTOR = {"read": "ai", "check": "code", "suggest_account": "ai", "investigate": "ai", "propose": "code", "await_approval": "person", "post": "code"}


class RunIn(BaseModel):
    invoice: str
    mode: Literal["replay", "scripted"] = "replay"


class DecisionIn(BaseModel):
    role: str
    decision: str
    reason: str = ""
    phone_confirmed: bool = False


@contextmanager
def session_conn(dbname: str, session: uuid.UUID) -> Iterator[psycopg.Connection]:
    """A pooled connection as ledger_app with the session set for one transaction, committed on success."""
    with pool(dbname, "ledger_app").connection() as conn:
        with conn.transaction():
            conn.execute("SELECT set_config('app.session_id', %s, true)", (str(session),))
            yield conn


def _new_usage(update: dict, seen: int) -> dict:
    """The model calls a step just made (model_usage is cumulative): model and tokens, for the audit row."""
    calls = (update.get("model_usage") or [])[seen:]
    if not calls:
        return {}
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return {"model": calls[-1].get("model"), "calls": len(calls), **{k: sum(c.get(k) or 0 for c in calls) for k in keys}}


def _step_detail(node: str, update: dict, seen: int) -> dict:
    d = _new_usage(update, seen)
    if node == "read":
        d.update(status=update.get("status", "read"), source_checks=update.get("source_checks", {}), reason=update.get("reason", ""))
    elif node == "check":
        d.update(status=update["status"], flags=[f["code"] for f in update["flags"]], approver=update["approver"], account=update.get("account"))
    elif node == "suggest_account":
        d.update(update["account_suggestion"])
    elif node == "investigate":
        d.update(explanation=update.get("explanation", "")[:400], email_draft=(update.get("email_draft") or {}).get("subject"))
    elif node == "propose":
        d.update(update["proposal"])
    return d


def create_api(dbname: str, docs_dir: Path | None = None, replays_dir: Path | None = None, keys: KeyPair | None = None, results_dir: Path | None = None, erp_url: str | None = None, erp_key: str | None = None, web_origin: str | None = None, mirror: Callable[[dict], dict] | None = None) -> FastAPI:
    api = FastAPI(title="ledger-desk", description="Accounts-payable demo for a fictional coffee roastery: sessions, runs and the audit log.")
    docs_dir = Path(docs_dir or ROOT / "out")
    replays_dir = Path(replays_dir or ROOT / "replays" / "claude-opus-5-5-low-run2")
    keys = keys or new_key_pair()
    results_dir = Path(results_dir or ROOT / "evals" / "results")
    if web_origin:
        # Two hostnames in production (docs/DEPLOY.md): only the page's own origin may call the API
        # from a browser. Locally the dev server proxies /api, one origin, and this stays off.
        api.add_middleware(
            CORSMiddleware,
            allow_origins=[web_origin],
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Session-Id"],
            allow_credentials=False,
        )
    company = build_company()
    # Locally the mock ERP runs in-process; deployed, it is its own container behind the same client,
    # reached over HTTP with its own key (settings.py).
    if erp_url:
        erp = ErpClient(httpx.Client(base_url=erp_url, timeout=15), api_key=erp_key or "")
    else:
        erp = ErpClient(TestClient(create_erp(dbname, api_key=ERP_KEY, approval_public_key=keys.public)), api_key=ERP_KEY, sleep=lambda s: None)
    url = url_for(dbname)
    # The checkpointer's connections come from a shared pool (db.pool). Each use gets its own PostgresSaver: the saver
    # holds a lock around every cursor (langgraph-checkpoint-postgres 3.2.1, __init__.py:485), so one shared saver
    # made every request wait its turn (measured: the browser tests went from about 1.0 to 1.9 minutes, 2 to 4 of 60
    # timing out, n=3 runs). A saver is a small object; the pool is what is shared.
    PostgresSaver(pool(dbname, "checkpoint")).setup()

    @contextmanager
    def checkpoints():
        yield PostgresSaver(pool(dbname, "checkpoint"))

    def graph(model, saver):
        return build_workflow(Deps(model=model, erp=erp, company=company, mirror=mirror), saver)

    def session_id(x_session_id: str | None = Header(default=None)) -> uuid.UUID:
        try:
            return uuid.UUID(x_session_id or "")
        except ValueError:
            raise HTTPException(401, "no session: POST /sessions first and send its id in X-Session-Id")

    def db(session: uuid.UUID = Depends(session_id)):
        with session_conn(dbname, session) as conn:
            if conn.execute("SELECT 1 FROM app.sessions WHERE id = %s", (session,)).fetchone() is None:
                raise HTTPException(404, "no such session; it may have expired")
            yield conn, session

    def run_view(conn, run_id: uuid.UUID, session: uuid.UUID) -> dict:
        row = conn.cursor(row_factory=dict_row).execute("SELECT id, sample, invoice_ref, mode, model, status FROM app.runs WHERE id = %s", (run_id,)).fetchone()
        if row is None:  # row-level security: another session's run is simply not there
            raise HTTPException(404, "no such run in this session")
        with checkpoints() as saver:
            state = graph(None, saver).get_state({"configurable": {"thread_id": f"{session}:{run_id}"}})
        pauses = [i.value for t in state.tasks for i in t.interrupts]
        values = state.values
        # A failed posting or a recording that no longer matches is recorded on app.runs by this API
        # (start_run, decide); the workflow's own state still holds the status from before the failure.
        status = row["status"] if row["status"] in ("post_failed", "failed") else values.get("status", row["status"])
        pause = pauses[0] if pauses else None
        held = conn.execute("SELECT i.status = 'on_hold' FROM app.runs r JOIN app.invoices i ON i.id = r.invoice_id WHERE r.id = %s", (run_id,)).fetchone()
        return {
            "run_id": str(row["id"]), "sample": row["sample"], "invoice_ref": row["invoice_ref"], "mode": row["mode"], "model": row["model"],
            "status": status, "paused": bool(pauses), "pause": pause, "flags": values.get("flags", []),
            "held": bool(held and held[0]),
            # what a finance team would do about the problem, while the bill waits for that decision (playbook.py)
            "next_step": suggested(conn, pause, values) if pause and pause.get("flags") else None,
            "reason": values.get("reason", ""), "metrics": values.get("metrics"), "entry_id": values.get("entry_id"), "mirror": values.get("mirror"),
            "extraction": values.get("extraction"), "source_checks": values.get("source_checks", {}), "email_draft": values.get("email_draft"), "lookups": values.get("lookups", []),
            "due_date": bill_due_date(values["extraction"], company) if values.get("extraction") else None,
            "seconds": recorded_seconds(row["sample"]) if row["mode"] == "replay" else None,
        }

    def suggested(conn, pause: dict, values: dict) -> dict | None:
        """The playbook's step, with the credit memos in this session's queue that name the bill (not
        rejected; row-level security keeps it to the session) and whether a vendor email was drafted."""
        e = values.get("extraction") or {}
        rows = conn.execute(
            """SELECT number, total FROM app.invoices WHERE extracted->>'kind' = 'credit_memo' AND extracted->>'refers_to' = %s
               AND vendor_name = %s AND status <> 'rejected' ORDER BY id""",
            (e.get("number") or "", e.get("vendor_name") or ""),
        ).fetchall()
        credits = [{"number": n, "total": str(t)} for n, t in rows]
        return next_step(pause["flags"], e, company, credits=credits, draft=bool(values.get("email_draft")))

    def recorded_seconds(sample: str) -> float | None:
        """How long the real run that a replay plays back took (Claude Code start-up included)."""
        path = replays_dir / f"{sample}.json"
        return json.loads(path.read_text(encoding="utf-8")).get("seconds") if path.exists() else None

    def results_file(name: str) -> Path:
        if not RESULT_NAME.fullmatch(name):
            raise HTTPException(404, "no such eval run")
        path = results_dir / f"{name}.json"
        if not path.is_file():
            raise HTTPException(404, "no such eval run")
        return path

    @api.get("/evals")
    def evals():
        """Every eval run's summary (public: fictional data only). A scripted run reads every
        invoice perfectly from the answer key, so it proves the graders and rules, not a model."""
        runs = []
        for path in sorted(results_dir.glob("*.json")) if results_dir.is_dir() else []:
            r = json.loads(path.read_text(encoding="utf-8"))
            runs.append({
                "name": path.stem, "version": r.get("version"), "tier": r.get("tier", "standard"), "model": r.get("model"), "date": r.get("date"),
                "proves": "the graders and the rules, not a model" if r.get("model") == "scripted" else "the model",
                "summary": r.get("summary"),
            })
        return {"runs": runs}

    @api.get("/evals/{name}")
    def eval_run(name: str):
        return json.loads(results_file(name).read_text(encoding="utf-8"))

    @api.get("/samples")
    def samples():
        """The 13 sample invoices a visitor can run, with what each one is there to show."""
        return {"samples": [
            {"id": c.id, "vendor_name": c.invoice.vendor_name, "number": c.invoice.number, "total": f"{c.invoice.total:.2f}",
             "document": c.document, "what_is_wrong": c.what_is_wrong, "replay": (replays_dir / f"{c.id}.json").exists()}
            for c in load_all()
        ]}

    @api.post("/sessions", status_code=201)
    def new_session():
        session = uuid.uuid4()
        with session_conn(dbname, session) as conn:
            conn.execute("INSERT INTO app.sessions (id) VALUES (%s)", (session,))
            audit_append(conn, session, "system", "session.created", str(session), {})
        return {"session_id": str(session)}

    @api.post("/runs", status_code=201)
    def start_run(body: RunIn, ctx=Depends(db, scope="function")):
        conn, session = ctx
        try:
            case = load_case(body.invoice)
        except FileNotFoundError:
            raise HTTPException(404, f"no sample invoice {body.invoice}; the ids are 01 to 13")
        # One run per sample per visitor: a reload, a second tab or a remount while the bill queue reads
        # would otherwise read the same bill twice, and the second copy passes every check (the duplicate
        # check looks at the company's paid bills). The lock holds until this transaction commits, so a
        # second request waits and then finds the first run. A failed run may be read again.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"run:{session}:{case.id}",))
        existing = conn.execute(
            "SELECT id FROM app.runs WHERE session_id = %s AND sample = %s AND status <> 'failed' ORDER BY created_at LIMIT 1", (session, case.id)
        ).fetchone()
        if existing:
            return JSONResponse(status_code=200, content=run_view(conn, existing[0], session))
        if body.mode == "replay":
            record_path = replays_dir / f"{case.id}.json"
            if not record_path.exists():
                raise HTTPException(404, f"no recorded run for invoice {case.id}")
            record = json.loads(record_path.read_text(encoding="utf-8"))
            model, model_name = ReplayModel(record["replies"]), record["model"]
        else:
            model, model_name = ScriptedReader(), "scripted"
            model.start(case)
        run_id = uuid.uuid4()
        ref = f"{case.id}-{run_id.hex[:8]}"
        conn.execute(
            "INSERT INTO app.runs (id, session_id, sample, invoice_ref, mode, model, status) VALUES (%s, %s, %s, %s, %s, %s, 'running')",
            (run_id, session, case.id, ref, body.mode, model_name),
        )
        audit_append(conn, session, "person", "run.started", ref, {"invoice": case.id, "mode": body.mode, "model": model_name})
        doc = render_case(case, docs_dir)
        config = {"configurable": {"thread_id": f"{session}:{run_id}"}}
        invoice_id, seen, status = None, 0, "running"
        try:
            with checkpoints() as saver:
                for chunk in graph(model, saver).stream({"document": str(doc), "invoice_ref": ref}, config, stream_mode="updates"):
                    node, update = next(iter(chunk.items()))
                    if node == "__interrupt__":
                        pause = update[0].value
                        audit_append(conn, session, "workflow", "run.paused", ref, {"status": pause["status"], "approver": pause["approver"]})
                        status = pause["status"]
                        continue
                    audit_append(conn, session, STEP_ACTOR.get(node, "code"), f"workflow.{node}", ref, _step_detail(node, update, seen))
                    seen = len(update.get("model_usage") or []) or seen
                    if node == "read" and "extraction" in update:
                        e = update["extraction"]
                        invoice_id = conn.execute(
                            "INSERT INTO app.invoices (session_id, vendor_name, number, status, total, po, extracted) VALUES (%s, %s, %s, 'read', %s, %s, %s) RETURNING id",
                            (session, e["vendor_name"], e["number"], e["total"], e.get("po"), json.dumps(e)),
                        ).fetchone()[0]
                        conn.execute("UPDATE app.runs SET invoice_id = %s WHERE id = %s", (invoice_id, run_id))
                    elif node == "read":
                        status = update.get("status", "manual_entry")
                    elif node == "check" and invoice_id is not None:
                        conn.execute("UPDATE app.invoices SET status = %s WHERE id = %s", (update["status"], invoice_id))
                        for f in update["flags"]:
                            conn.execute(
                                "INSERT INTO app.checks (session_id, invoice_id, code, passed, detail) VALUES (%s, %s, %s, false, %s)",
                                (session, invoice_id, f["code"], f["detail"]),
                            )
        except ReplayMismatch as e:
            audit_append(conn, session, "workflow", "run.failed", ref, {"error": str(e)})
            conn.execute("UPDATE app.runs SET status = 'failed' WHERE id = %s", (run_id,))
            return JSONResponse(status_code=409, content={"detail": f"the recorded run no longer matches the code: {e}"})  # returned so the audit row commits
        if status == "manual_entry":
            audit_append(conn, session, "workflow", "run.ended", ref, {"status": status})
        conn.execute("UPDATE app.runs SET status = %s WHERE id = %s", (status, run_id))
        return run_view(conn, run_id, session)

    @api.post("/runs/{run_id}/decision")
    def decide(run_id: uuid.UUID, body: DecisionIn, ctx=Depends(db, scope="function")):
        conn, session = ctx
        view = run_view(conn, run_id, session)  # 404 for another session's run
        if not view["paused"]:
            raise HTTPException(409, f"the run is not waiting for a decision (status {view['status']})")
        pause, ref = view["pause"], view["invoice_ref"]
        refusal = check_decision(pause, body.role, body.decision, body.reason, body.phone_confirmed)
        if refusal:
            # A refused attempt is on record too. Returned, not raised: raising would roll the
            # request's transaction back and take this audit row with it.
            audit_append(conn, session, "person", "approval.refused", ref, {"role": body.role, "decision": body.decision, "status": refusal.status, "why": refusal.message})
            return JSONResponse(status_code=refusal.status, content={"detail": refusal.message})
        invoice_id = conn.execute("SELECT invoice_id FROM app.runs WHERE id = %s", (run_id,)).fetchone()[0]
        signature = sign(keys.private, ref, body.role, pause["proposal"]["lines"]) if body.decision == "approve" else None
        conn.execute(
            "INSERT INTO app.approvals (session_id, invoice_id, role, decision, reason, phone_confirmed, signature) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (session, invoice_id, body.role, body.decision, body.reason or None, body.phone_confirmed, signature),
        )
        audit_append(conn, session, "person", f"approval.{body.decision}", ref, {"role": body.role, "reason": body.reason, "phone_confirmed": body.phone_confirmed})
        if body.decision == "hold":  # the run stays paused: a held invoice can still be approved or rejected later
            conn.execute("UPDATE app.invoices SET status = 'on_hold' WHERE id = %s", (invoice_id,))
            return run_view(conn, run_id, session)
        config = {"configurable": {"thread_id": f"{session}:{run_id}"}}
        resume = {"decision": body.decision, "approver": body.role, "reason": body.reason, "signature": signature}
        try:
            with checkpoints() as saver:
                for chunk in graph(None, saver).stream(Command(resume=resume), config, stream_mode="updates"):
                    node, update = next(iter(chunk.items()))
                    if node == "post":
                        audit_append(conn, session, "code", "workflow.post", ref, {"entry_id": update.get("entry_id"), "status": update.get("status")})
                    elif node == "mirror":  # the QuickBooks sandbox copy, or why it failed (docs/decisions/0006)
                        audit_append(conn, session, "code", "workflow.mirror", ref, update["mirror"])
        except (ApprovalRejected, EntryRejected, EntryConflict, ErpUnavailable) as e:
            # Nothing posted. Recorded and returned (not raised, so the audit row commits); the run
            # can post again later with the same idempotency key.
            audit_append(conn, session, "code", "workflow.post_failed", ref, {"error": f"{type(e).__name__}: {str(e)[:200]}"})
            conn.execute("UPDATE app.runs SET status = 'post_failed' WHERE id = %s", (run_id,))
            return JSONResponse(status_code=502, content={"detail": f"the ERP refused the posting ({type(e).__name__}); nothing was posted"})
        final = run_view(conn, run_id, session)
        audit_append(conn, session, "workflow", f"run.{final['status']}", ref, {"entry_id": final.get("entry_id")})
        conn.execute("UPDATE app.runs SET status = %s WHERE id = %s", (final["status"], run_id))
        conn.execute("UPDATE app.invoices SET status = %s WHERE id = %s", (final["status"], invoice_id))
        return final

    @api.get("/runs/{run_id}/document")
    def document(run_id: uuid.UUID, ctx=Depends(db, scope="function")):
        """The PDF or photo the run read. Behind the session header like everything else, so the
        browser fetches it and shows it from a blob URL."""
        conn, _ = ctx
        row = conn.execute("SELECT sample FROM app.runs WHERE id = %s", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such run in this session")
        path = render_case(load_case(row[0]), docs_dir)
        media = "application/pdf" if Path(path).suffix.lower() == ".pdf" else "image/jpeg"
        return FileResponse(path, media_type=media)

    @api.get("/runs/{run_id}")
    def get_run(run_id: uuid.UUID, ctx=Depends(db, scope="function")):
        conn, session = ctx
        return run_view(conn, run_id, session)

    @api.get("/invoices")
    def invoices(ctx=Depends(db, scope="function")):
        conn, _ = ctx
        rows = conn.cursor(row_factory=dict_row).execute(
            """SELECT i.id, i.number, i.vendor_name, i.status, i.total, r.id AS run_id,
                      coalesce(array_agg(c.code ORDER BY c.id) FILTER (WHERE c.code IS NOT NULL), '{}') AS flags
               FROM app.invoices i
               LEFT JOIN app.runs r ON r.invoice_id = i.id
               LEFT JOIN app.checks c ON c.invoice_id = i.id AND NOT c.passed
               GROUP BY i.id, r.id ORDER BY i.id"""
        ).fetchall()
        return {"invoices": [{**r, "total": f"{r['total']:.2f}", "run_id": str(r["run_id"]) if r["run_id"] else None} for r in rows]}

    @api.get("/audit")
    def audit(ctx=Depends(db, scope="function")):
        conn, _ = ctx
        rows = conn.cursor(row_factory=dict_row).execute("SELECT id, session_id, at, actor, action, entity, detail, prev_hash, hash FROM app.audit_log ORDER BY id").fetchall()
        return {"entries": [{**r, "session_id": str(r["session_id"]), "at": r["at"].isoformat()} for r in rows]}

    @api.post("/audit/tamper")
    def tamper(ctx=Depends(db, scope="function")):
        """For the demo: edit this visitor's newest audit row the way only the database owner
        could, behind the app's back, so "Verify audit log" has something to find. It uses the
        owner's connection on purpose (the app's role has no UPDATE on audit_log) and touches no
        other session's rows."""
        _, session = ctx
        with psycopg.connect(url) as owner:
            edited = owner.execute(
                "UPDATE app.audit_log SET detail = detail || '{\"edited\": \"behind the app''s back\"}'::jsonb "
                "WHERE id = (SELECT max(id) FROM app.audit_log WHERE session_id = %s) RETURNING id",
                (session,),
            ).fetchone()[0]
        return {"edited_id": edited}

    @api.get("/audit/verify")
    def verify(ctx=Depends(db, scope="function")):
        conn, session = ctx
        rows = conn.execute("SELECT count(*) FROM app.audit_log").fetchone()[0]
        bad = audit_verify(conn, session)
        return {"intact": bad is None, "rows": rows, "first_bad_id": bad}

    return api
