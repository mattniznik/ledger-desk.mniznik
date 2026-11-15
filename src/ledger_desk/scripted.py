"""The reading a perfect reader would return for each sample invoice, built from its YAML ground
truth, with each field's source text exactly as the PDF prints it.

Used by the tests' fakes and by `ledger-desk run --model scripted`, which runs the whole workflow
with no model so the pipeline can be shown and graded for $0. Anything it produces is labelled
scripted wherever it is shown.
"""

from __future__ import annotations

from .invoices import Case


def usd(value) -> str:
    return f"${value:,.2f}" if value >= 0 else f"-${-value:,.2f}"


def perfect_reading(case: Case, **overrides) -> dict:
    inv = case.invoice
    reading = {
        "kind": inv.kind,
        "vendor_name": inv.vendor_name,
        "vendor_tax_id": inv.vendor_tax_id,
        "number": inv.number,
        "date": inv.date.isoformat(),
        "po": inv.po,
        "refers_to": inv.refers_to,
        "remit_bank": inv.remit_to.bank,
        "remit_account_last4": inv.remit_to.account_last4,
        "lines": [
            {"description": l.description, "quantity": str(l.quantity), "unit_price": str(l.unit_price), "amount": str(l.amount), "po_line": l.po_line}
            for l in inv.lines
        ],
        "subtotal": str(inv.subtotal),
        "tax": str(inv.tax),
        "total": str(inv.total),
        "notes": list(inv.notes),
        "sources": {
            "number": inv.number,
            "date": inv.date.isoformat(),
            "total": usd(inv.total),
            "vendor_tax_id": inv.vendor_tax_id,
            "remit_account_last4": f"account ending {inv.remit_to.account_last4}",
            **({"po": inv.po} if inv.po else {}),
        },
    }
    reading.update(overrides)
    return reading
