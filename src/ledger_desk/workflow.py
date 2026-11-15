"""One invoice's run as a LangGraph graph (docs/decisions/0001).

    read -> check -> [suggest_account, bills without a PO] -> [investigate, exceptions only]
         -> propose -> await_approval -> post -> [mirror, when switched on and posted]
      '--> manual_entry (refusal or unreadable): the run ends and a person types the fields

`mirror` (docs/decisions/0006) copies a posted bill to the QuickBooks sandbox. The mock ERP stays the system of
record: the mirror runs only after a posting, and a failure there is recorded on the run, never
raised, so it cannot undo or block the posting. Without a mirror the graph has no such step.

`await_approval` pauses the run with `interrupt()` until a person decides; the run is resumed with
`Command(resume=decision)` on the same thread id. LangGraph's docs (interrupts, read 2026-11-14):
"the runtime restarts the entire node from the beginning", and side effects belong after the
interrupt or in a separate node. So posting is its own node, and its idempotency key is made from
the invoice and the approval signature: if the posting step runs again after a crash, the ERP
returns the entry it already has instead of writing a second one.

State holds only plain JSON values (strings for money), so any checkpointer can store it, the
Postgres one included.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .accounts import suggest_account
from .agent import ReadOnlyErp, agent_tools, investigate
from .company import Company, due_date
from .erp.client import ErpClient
from .model import ModelClient, summarize
from .reading import Extraction, document_text, read_invoice, to_invoice
from .rules import check

AP_ACCOUNT = "2000"


@dataclass
class Deps:
    model: ModelClient
    erp: ErpClient
    company: Company
    after_post: Callable[[Any], None] | None = None  # tests use it to crash right after the ERP wrote
    mirror: Callable[[dict], dict] | None = None  # posted bill -> QuickBooks sandbox (quickbooks.mirror_bill)


class RunState(TypedDict, total=False):
    document: str
    invoice_ref: str
    status: str
    reason: str
    extraction: dict
    source_checks: dict
    flags: list
    approver: str
    controller_only: bool
    account: str | None
    account_suggestion: dict
    explanation: str
    email_draft: dict | None
    lookups: list[dict]  # the agent's lookups: tool, input, one-line result (agent.lookup_result)
    proposal: dict
    approval: dict
    entry_id: int
    mirror: dict
    model_usage: list
    metrics: dict


def bill_due_date(extraction: dict, company: Company) -> str | None:
    """When the bill is due: its printed date plus the vendor's terms. None for a credit memo (it is
    not paid, it reduces what is owed) and for a vendor not in the vendor master (no terms)."""
    vendor = company.vendor_by_tax_id(extraction.get("vendor_tax_id")) or company.vendor_by_name(extraction["vendor_name"])
    if vendor is None or Decimal(extraction["total"]) < 0:
        return None
    return due_date(extraction["date"], vendor.terms_days)


def mirror_request(state: RunState, company: Company) -> dict:
    """The posted entry as the mirror needs it: the vendor's own name from the vendor master, the
    printed number and date, the due date from the vendor's terms, and the expense side of the entry
    (accounts payable is the accounting system's own side of a bill, so it is never a line)."""
    if state.get("status") != "posted" or not state.get("entry_id"):
        raise ValueError("only a posted entry is mirrored")
    e = state["extraction"]
    vendor = company.vendor_by_tax_id(e.get("vendor_tax_id")) or company.vendor_by_name(e["vendor_name"])
    names = {a.number: a.name for a in company.accounts}
    credit = Decimal(e["total"]) < 0
    description = "; ".join(line["description"] for line in e.get("lines", [])) or e["number"]
    lines = [
        {"account": line["account"], "account_name": names.get(line["account"], line["account"]), "amount": line["credit"] if credit else line["debit"], "description": description}
        for line in state["proposal"]["lines"]
        if line["account"] != AP_ACCOUNT
    ]
    return {
        "kind": "credit" if credit else "bill",
        "vendor": vendor.name if vendor else e["vendor_name"],
        "number": e["number"],
        "date": e["date"],
        "due_date": bill_due_date(e, company),
        "lines": lines,
        "note": f"Ledger Desk {state['invoice_ref']}, ERP entry {state['entry_id']}",
    }


def _usage(state: RunState, new: list[dict]) -> dict:
    usage = list(state.get("model_usage", [])) + new
    return {"model_usage": usage, "metrics": summarize(usage)}


def _needs_account(state: RunState) -> bool:
    """A bill with no PO is coded by suggestion; a credit memo follows its original and a duplicate is not coded."""
    e = state["extraction"]
    return e.get("po") is None and e.get("kind") == "invoice" and not any(f["code"] == "DUPLICATE" for f in state.get("flags", []))


def _after_coding(state: RunState) -> str:
    return "investigate" if state["status"] == "exception" else "propose"


def build_workflow(deps: Deps, checkpointer):
    def read(state: RunState):
        result = read_invoice(Path(state["document"]), deps.model)
        out = _usage(state, result.usage)
        if result.status != "read":
            return {**out, "status": "manual_entry", "reason": result.reason}
        return {**out, "extraction": result.extraction.model_dump(), "source_checks": result.source_checks}

    def check_node(state: RunState):
        invoice = to_invoice(Extraction.model_validate(state["extraction"]))
        result = check(invoice, deps.company, document_text(Path(state["document"])))
        flags = [
            {"code": f.code, "detail": f.detail, "amount": None if f.amount is None else str(f.amount), "quantity": None if f.quantity is None else str(f.quantity)}
            for f in result.flags
        ]
        missing = sorted(k for k, v in state.get("source_checks", {}).items() if v == "missing")
        if missing:
            flags.append({"code": "SOURCE_NOT_FOUND", "detail": f"not found in the document as read: {', '.join(missing)}", "amount": None, "quantity": None})
        return {
            "flags": flags,
            "status": "exception" if flags else "ready",
            "approver": result.approver,
            "controller_only": result.controller_only,
            "account": result.account,
        }

    def suggest_node(state: RunState):
        invoice = to_invoice(Extraction.model_validate(state["extraction"]))
        s = suggest_account(invoice, deps.company, deps.model)
        return {**_usage(state, s.usage), "account": s.account, "account_suggestion": s.as_state()}

    def investigate_node(state: RunState):
        invoice = to_invoice(Extraction.model_validate(state["extraction"]))
        drafts: list = []
        result = investigate(invoice, state["flags"], deps.model, agent_tools(ReadOnlyErp(deps.erp), drafts), drafts)
        return {**_usage(state, result.usage), "explanation": result.explanation, "email_draft": result.email_draft, "lookups": result.lookups}

    def propose(state: RunState):
        total = Decimal(state["extraction"]["total"])
        account = state.get("account")
        if not account or account == "split":
            return {"proposal": {"lines": [], "note": "no single account; a person codes this invoice"}}
        amount = f"{abs(total):.2f}"
        expense = {"account": account, "debit": amount, "credit": "0.00"}
        payable = {"account": AP_ACCOUNT, "debit": "0.00", "credit": amount}
        if total < 0:  # a credit memo reverses the usual entry
            expense = {"account": AP_ACCOUNT, "debit": amount, "credit": "0.00"}
            payable = {"account": account, "debit": "0.00", "credit": amount}
        return {"proposal": {"lines": [expense, payable]}}

    def await_approval(state: RunState):
        decision = interrupt(
            {
                "invoice_ref": state["invoice_ref"],
                "status": state["status"],
                "flags": state.get("flags", []),
                "approver": state.get("approver"),
                "proposal": state["proposal"],
                "explanation": state.get("explanation", ""),
                "controller_only": state.get("controller_only", False),
                "total": state["extraction"]["total"],
                "account_suggestion": state.get("account_suggestion"),
            }
        )
        return {"approval": decision}

    def post(state: RunState):
        approval = state["approval"]
        if approval.get("decision") != "approve":
            return {"status": "rejected" if approval.get("decision") == "reject" else "on_hold"}
        key = hashlib.sha256(f"{state['invoice_ref']}|{approval['signature']}".encode()).hexdigest()[:40]
        entry = {
            "invoice_ref": state["invoice_ref"],
            "lines": state["proposal"]["lines"],
            "approval": {"approver": approval["approver"], "signature": approval["signature"]},
        }
        result = deps.erp.post_journal_entry(entry, idempotency_key=key)
        if deps.after_post:
            deps.after_post(result["id"])
        return {"entry_id": result["id"], "status": "posted"}

    def mirror(state: RunState):
        try:
            result = deps.mirror(mirror_request(state, deps.company))
        except Exception as e:  # recorded, never raised: the posting already stands in the ERP
            return {"mirror": {"status": "failed", "error": f"{type(e).__name__}: {str(e)[:300]}"}}
        return {"mirror": {"status": "mirrored", **result}}

    graph = StateGraph(RunState)
    graph.add_node("read", read)
    graph.add_node("check", check_node)
    graph.add_node("suggest_account", suggest_node)
    graph.add_node("investigate", investigate_node)
    graph.add_node("propose", propose)
    graph.add_node("await_approval", await_approval)
    graph.add_node("post", post)
    graph.add_edge(START, "read")
    graph.add_conditional_edges("read", lambda s: END if s.get("status") == "manual_entry" else "check")
    graph.add_conditional_edges("check", lambda s: "suggest_account" if _needs_account(s) else _after_coding(s))
    graph.add_conditional_edges("suggest_account", _after_coding)
    graph.add_edge("investigate", "propose")
    graph.add_edge("propose", "await_approval")
    graph.add_edge("await_approval", "post")
    if deps.mirror is None:
        graph.add_edge("post", END)
    else:
        graph.add_node("mirror", mirror)
        graph.add_conditional_edges("post", lambda s: "mirror" if s.get("status") == "posted" else END)
        graph.add_edge("mirror", END)
    return graph.compile(checkpointer=checkpointer)
