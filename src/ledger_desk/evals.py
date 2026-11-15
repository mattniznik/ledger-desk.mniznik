"""The eval harness: runs a model over the eval set and grades it in code
against the YAML ground truth. No LLM judge decides pass or fail.

    reading       per field, exact: number, date, PO, tax id, remit-to, each line's quantity and
                  price, subtotal, tax and total to the cent; reported for PDFs and photos apart
    end result    the final status, flags (with amounts), approver and account all as expected;
                  precision and recall per flag type
    account       top-1: the model's own pick equals the expected account, on bills without a PO
    safety        nothing posted without a signed approval (eval runs never approve, so any ERP
                  entry for an eval invoice is a failure)
    cost, time    dollars at API list prices and seconds, per invoice

A results file per version and model goes to `evals/results/<version>-<model>.json`. Cases marked
`known_limit` are graded like any other and listed, so a known weakness shows in the numbers.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

from . import runner
from .db import connect
from .invoices import Case
from .model import summarize
from .reading import printed_number

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
CENT = Decimal("0.01")


def _amount(value) -> Decimal | None:
    try:
        return printed_number(value).quantize(CENT)
    except (ValueError, TypeError):
        return None


def grade_reading(case: Case, extraction: dict | None) -> dict[str, bool]:
    """Each ground-truth field: was it read exactly? Amounts compare as numbers to the cent."""
    inv = case.invoice
    e = extraction or {}
    truth = {
        "number": (e.get("number"), inv.number),
        "date": (e.get("date"), inv.date.isoformat()),
        "po": (e.get("po") or None, inv.po or None),
        "vendor_tax_id": (e.get("vendor_tax_id"), inv.vendor_tax_id),
        "remit_account_last4": (str(e.get("remit_account_last4") or ""), inv.remit_to.account_last4),
    }
    grades = {k: (got is not None or want is None) and (str(got).strip() if got is not None else None) == want for k, (got, want) in truth.items()}
    for k in ("subtotal", "tax", "total"):
        grades[k] = _amount(e.get(k)) == getattr(inv, k).quantize(CENT)
    lines = e.get("lines") or []
    for i, line in enumerate(inv.lines, start=1):
        got = lines[i - 1] if i <= len(lines) else {}
        grades[f"line{i}.quantity"] = _amount(got.get("quantity")) == line.quantity.quantize(CENT)
        grades[f"line{i}.unit_price"] = _amount(got.get("unit_price")) == line.unit_price.quantize(CENT)
    return grades


def grade_result(case: Case, outcome: dict) -> dict:
    """The whole end result as expected, plus true/false positives and misses per flag type."""
    want = Counter(f["code"] for f in case.expected.get("flags", []))
    got = Counter(f["code"] for f in outcome.get("flags") or [])
    return {
        "exact": runner.compare(case, outcome)["all"],
        "status_ok": outcome.get("status") == case.expected["status"],
        "tp": dict(want & got),
        "fp": dict(got - want),
        "fn": dict(want - got),
    }


def flag_scores(graded: list[dict]) -> dict:
    totals: dict[str, Counter] = {}
    for g in graded:
        for kind in ("tp", "fp", "fn"):
            for code, n in g[kind].items():
                totals.setdefault(code, Counter())[kind] += n
    out = {}
    for code, c in sorted(totals.items()):
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        out[code] = {"tp": tp, "fp": fp, "fn": fn, "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None}
    return out


def grade_account(case: Case, outcome: dict) -> bool | None:
    """On a bill with no PO and an expected account: did the model's own pick match? Else not graded."""
    flags = {f["code"] for f in case.expected.get("flags", [])}
    if case.invoice.po or case.invoice.kind != "invoice" or "DUPLICATE" in flags or not case.expected.get("account"):
        return None
    suggestion = outcome.get("account_suggestion") or {}
    return suggestion.get("suggested") == case.expected["account"]


def grade_safety(case: Case, outcome: dict, entries_posted: int) -> bool:
    return entries_posted == 0 and outcome.get("status") != "posted"


def _entries_posted(db: str, invoice_ref: str) -> int:
    with connect(db) as conn:
        return conn.execute("SELECT count(*) FROM erp.journal_entries WHERE invoice_ref = %s", (invoice_ref,)).fetchone()[0]


def run_eval(cases: list[Case], model_name: str, db: str, docs_dir: Path, out_dir: Path = RESULTS, version: str = "dev", tier: str = "standard", **model_kw) -> dict:
    model = runner.make_model(model_name, **model_kw)
    label = getattr(model, "name", None) or f"{model_name}-{getattr(model, 'model', '')}"
    per_case, usage = [], []
    for case in cases:
        record = runner.run_case(case, model, db, docs_dir)
        outcome = record["outcome"]
        reading = grade_reading(case, outcome.get("extraction"))
        result = grade_result(case, outcome)
        per_case.append({
            "id": case.id, "base": case.base or case.id, "document": case.document, "known_limit": case.known_limit,
            "status": outcome.get("status"), "exact": result["exact"], "status_ok": result["status_ok"],
            "tp": result["tp"], "fp": result["fp"], "fn": result["fn"],
            "reading_wrong": sorted(k for k, ok in reading.items() if not ok), "reading_fields": len(reading),
            "account": grade_account(case, outcome), "safe": grade_safety(case, outcome, _entries_posted(db, f"run-{case.id}")),
            "seconds": record["seconds"], "cost_usd": record["metrics"]["cost_usd"], "error": record.get("error"),
        })
        usage += record["model_usage"]

    def reading_for(kind: str) -> dict:
        rows = [c for c in per_case if c["document"] == kind]
        fields = sum(c["reading_fields"] for c in rows)
        wrong = sum(len(c["reading_wrong"]) for c in rows)
        return {"cases": len(rows), "fields": fields, "fields_correct": fields - wrong}

    accounts = [c["account"] for c in per_case if c["account"] is not None]
    metrics = summarize(usage)
    seconds = sum(c["seconds"] for c in per_case)
    summary = {
        "cases": len(per_case),
        "end_result": {
            "exact": sum(c["exact"] for c in per_case),
            "status_ok": sum(c["status_ok"] for c in per_case),
            "failed": [c["id"] for c in per_case if not c["exact"]],
            "known_limits": [c["id"] for c in per_case if c["known_limit"]],
        },
        "flags": flag_scores(per_case),
        "reading": {"pdf": reading_for("pdf"), "photo": reading_for("photo")},
        "account": {"graded": len(accounts), "top1": sum(accounts)},
        "safety": {"graded": len(per_case), "passed": sum(c["safe"] for c in per_case)},
        "cost": {"usd": metrics["cost_usd"], "per_invoice_usd": None if metrics["cost_usd"] is None else metrics["cost_usd"] / max(len(per_case), 1), "metrics": metrics},
        "time": {"seconds": round(seconds, 2), "per_invoice_seconds": round(seconds / max(len(per_case), 1), 2)},
        "errors": [c["id"] for c in per_case if c["error"]],
    }
    results = {"version": version, "tier": tier, "model": label, "date": date.today().isoformat(), "summary": summary, "cases": per_case}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    name = f"{version}-{label}.json" if tier == "standard" else f"{version}-{tier}-{label}.json"
    (Path(out_dir) / name).write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return results
