"""Run-and-record: the sample invoices through the workflow, compared with their ground truth.

Each invoice runs to the approval pause (or to manual entry), the way a visitor would see it before
deciding. The record holds the outcome, the comparison with the expected result, the time, the
usage, and every model reply in order. Those replies make the record a replay: `ReplayModel`
plays them back through the same code (reading checks, rules, workflow), so the demo and the evals
can show a real run again for $0. If the code asks the model something the recording does not
have, the replay stops (`ReplayMismatch`) rather than pairing a reply with the wrong question.

The ERP is the local database's, in-process (no server); nothing is posted, so the approval key
pair is a throwaway one.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from .approval import new_key_pair
from .company import Company, build_company
from .documents import render_case
from .erp.app import create_app
from .erp.client import ErpClient
from .invoices import Case
from .model import ModelClient, ModelReply, ToolCall, summarize
from .scripted import perfect_reading
from .workflow import Deps, build_workflow

LOCAL_API_KEY = "local-dev-key"  # in-process only; not a secret
OUTCOME_KEYS = ("status", "reason", "flags", "approver", "controller_only", "account", "account_suggestion", "explanation", "email_draft", "lookups", "proposal", "source_checks", "extraction")


class ReplayMismatch(RuntimeError):
    """The code asked the model for something the recording does not hold at that point."""


def reply_to_dict(reply: ModelReply) -> dict:
    return asdict(reply)


def reply_from_dict(d: dict) -> ModelReply:
    return ModelReply(d["stop_reason"], d.get("text", ""), [ToolCall(**c) for c in d.get("tool_calls", [])], dict(d.get("usage", {})), d.get("model", ""))


class ScriptedReader:
    """No model: reads every invoice perfectly from its ground truth, suggests the expected account,
    explains in one fixed sentence. `overrides` changes a reading, to test what the checks catch."""

    name = "scripted"
    via = "scripted"

    def __init__(self, overrides: dict | None = None):
        self.overrides = overrides or {}
        self.case: Case | None = None

    def start(self, case: Case) -> None:
        self.case = case

    def __call__(self, request: dict) -> ModelReply:
        usage = {"input_tokens": 0, "output_tokens": 0}
        task = request["task"]
        if task == "read":
            reading = perfect_reading(self.case, **self.overrides.get(self.case.id, {}))
            return ModelReply("end_turn", json.dumps(reading), usage=usage, model="scripted")
        if task == "suggest_account":
            account = self.case.expected.get("account") or "6400"
            return ModelReply("end_turn", json.dumps({"account": account, "reason": "Scripted: the expected account."}), usage=usage, model="scripted")
        codes = ", ".join(f["code"] for f in json.loads(request["messages"][0]["content"].split("\n", 1)[1])["flags"])
        return ModelReply("end_turn", f"Scripted explanation, no model: flagged {codes}.", usage=usage, model="scripted")


class ReplayModel:
    name = "replay"
    via = "replay"

    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.used = 0

    @property
    def remaining(self) -> int:
        return len(self.replies) - self.used

    def __call__(self, request: dict) -> ModelReply:
        if self.used >= len(self.replies):
            raise ReplayMismatch(f"the code asked for '{request['task']}' after the recording's {len(self.replies)} replies")
        rec = self.replies[self.used]
        if rec["task"] != request["task"]:
            raise ReplayMismatch(f"reply {self.used + 1} was recorded for '{rec['task']}', the code asked for '{request['task']}'")
        self.used += 1
        return reply_from_dict(rec["reply"])


class _Recorder:
    def __init__(self, model: ModelClient):
        self.model = model
        self.replies: list[dict] = []

    def __call__(self, request: dict) -> ModelReply:
        reply = self.model(request)
        self.replies.append({"task": request["task"], "reply": reply_to_dict(reply)})
        return reply


def make_model(name: str, model_id: str = "claude-opus-5-5", effort: str = "low") -> ModelClient:
    if name == "scripted":
        return ScriptedReader()
    if name == "subscription":
        from .subscription import ClaudeCodeModel

        return ClaudeCodeModel(model=model_id, effort=effort)
    if name == "api":  # the deployed demo's client; needs LEDGER_DESK_ANTHROPIC_KEY in .env.local
        from .anthropic_api import AnthropicModel

        return AnthropicModel(model=model_id, effort=effort)
    raise ValueError(f"unknown model '{name}': scripted, subscription or api")


def _flag_key(f: dict) -> tuple:
    d = lambda v: None if v is None else Decimal(str(v))  # noqa: E731
    return (f["code"], d(f.get("amount")), d(f.get("quantity")))


def compare(case: Case, outcome: dict) -> dict:
    exp = case.expected
    m = {
        "status": outcome.get("status") == exp["status"],
        "flags": {_flag_key(f) for f in outcome.get("flags") or []} == {_flag_key(f) for f in exp.get("flags", [])},
        "approver": outcome.get("approver") == exp["approver"],
        "account": outcome.get("account") == exp.get("account"),
    }
    m["all"] = all(m.values())
    return m


def run_case(case: Case, model: ModelClient, db: str, docs_dir, company: Company | None = None) -> dict:
    doc = render_case(case, Path(docs_dir))
    app = create_app(db, api_key=LOCAL_API_KEY, approval_public_key=new_key_pair().public)
    erp = ErpClient(TestClient(app), api_key=LOCAL_API_KEY, sleep=lambda s: None)
    recorder = _Recorder(model)
    if hasattr(model, "start"):
        model.start(case)
    graph = build_workflow(Deps(model=recorder, erp=erp, company=company or build_company()), InMemorySaver())

    state: dict = {}
    error = None
    started = time.perf_counter()
    try:
        state = graph.invoke({"document": str(doc), "invoice_ref": f"run-{case.id}"}, {"configurable": {"thread_id": f"run-{case.id}-{uuid.uuid4().hex[:8]}"}})
    except ReplayMismatch:
        raise
    except Exception as e:  # one invoice failing is a result to record, not the end of the run
        error = f"{type(e).__name__}: {str(e)[:300]}"
    seconds = round(time.perf_counter() - started, 2)

    outcome = {k: state[k] for k in OUTCOME_KEYS if k in state}
    usage = state.get("model_usage") or [{"model": r["reply"]["model"], **r["reply"]["usage"]} for r in recorder.replies]
    record = {
        "id": case.id,
        "slug": case.slug,
        "document": Path(doc).name,
        "model": getattr(model, "name", None) or getattr(model, "model", "unknown"),
        "via": getattr(model, "via", "unknown"),
        "date": date.today().isoformat(),
        "seconds": seconds,
        "outcome": outcome,
        "expected": case.expected,
        "match": compare(case, outcome) if error is None else {"status": False, "flags": False, "approver": False, "account": False, "all": False},
        "metrics": summarize(usage),
        "model_usage": usage,
        "replies": recorder.replies,
    }
    if error:
        record["error"] = error
    return record


def summary_of(records: list[dict]) -> dict:
    usage = [u for r in records for u in r["model_usage"]]
    return {
        "date": date.today().isoformat(),
        "model": records[0]["model"] if records else None,
        "via": records[0]["via"] if records else None,
        "total": len(records),
        "matched": sum(r["match"]["all"] for r in records),
        "errors": sum("error" in r for r in records),
        "seconds": round(sum(r["seconds"] for r in records), 2),
        "metrics": summarize(usage),
        "invoices": {r["id"]: {"match": r["match"]["all"], "status": r["outcome"].get("status"), "seconds": r["seconds"], "cost_usd": r["metrics"]["cost_usd"], **({"error": r["error"]} if "error" in r else {})} for r in records},
    }


def write_record(record: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{record['id']}.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
