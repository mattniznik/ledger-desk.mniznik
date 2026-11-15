"""The checking rules: plain Python over an invoice's fields and the ERP's records.

This is the demo's main argument (docs/decisions/0002): arithmetic, matching, tolerances,
duplicates and bank changes are done by code, because code gives the same answer every time and
an auditor can re-run it. No model is involved here. The fields come from Claude's reading of the PDF
(reading.py); the rules do not depend on where they came from.

Each check adds a Flag with a code a person and a test can both read. An invoice with no flags is
"ready"; any flag makes it an "exception". Either way a person approves before anything posts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .company import Company, Vendor, money
from .invoices import Invoice

# Policies. One place; the How it works page quotes them.
PRICE_TOLERANCE = Decimal("0.02")  # a line passes within 2% of the PO price, inclusive
RECURRING_TOLERANCE = Decimal("0.25")  # recurring bills without a PO: within 25% of the average
RECURRING_WINDOW = 3  # trailing bills that make the average
CONTROLLER_FROM = Decimal("5000.00")  # $5,000 and over goes to the controller
CAPITAL_ACCOUNT = "1500"  # capitalized items go to the controller

# Text that addresses an AI or claims approval. Invoice text is data, never instructions; this
# check makes such text visible to the person instead of trusting any reader to ignore it.
# A short keyword list, so it catches the obvious cases only (stated in the README).
SUSPICIOUS = [
    re.compile(r"\b(ai|a\.i\.)\s+(systems?|assistants?|agents?|models?)\b", re.I),
    re.compile(r"\bpre-?approved\b", re.I),
    re.compile(r"\bignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions?\b", re.I),
    re.compile(r"\b(post|pay|approve)\s+(it|this|this\s+invoice)\s+(now|immediately)\b", re.I),
]


@dataclass
class Flag:
    code: str
    detail: str
    amount: Decimal | None = None
    quantity: Decimal | None = None


@dataclass
class Result:
    status: str  # "ready" or "exception"
    flags: list[Flag] = field(default_factory=list)
    approver: str = "clerk"  # "clerk" or "controller"
    account: str | None = None  # proposed debit account; "split" when lines differ
    controller_only: bool = False
    phone_check: bool = False


def _arithmetic(inv: Invoice) -> list[Flag]:
    flags = []
    for i, line in enumerate(inv.lines, start=1):
        if money(line.quantity * line.unit_price) != line.amount:
            flags.append(Flag("TOTALS_MISMATCH", f"line {i}: {line.quantity} x {line.unit_price} is not {line.amount}"))
    line_sum = sum((l.amount for l in inv.lines), Decimal(0))
    if line_sum != inv.subtotal or inv.subtotal + inv.tax != inv.total:
        gap = abs(inv.total - (line_sum + inv.tax))
        flags.append(Flag("TOTALS_MISMATCH", f"lines {line_sum} + tax {inv.tax} = {line_sum + inv.tax}, printed total {inv.total}", amount=gap))
    return flags[-1:] if flags else []


def _suspicious(inv: Invoice, document_text: str | None = None) -> list[Flag]:
    # The printed page first, read by code: measured 2026-11-14 (n=2 real runs), the model returned
    # invoice 12's footer as its own commentary, so a check on the reading alone depends on how the
    # model chose to transcribe it. The flag then quotes the page, not the model's account of it.
    # A photo has no text layer, so for it the reading is all there is.
    printed = [line.strip() for line in (document_text or "").splitlines() if line.strip()]
    texts = printed + list(inv.notes) + [l.description for l in inv.lines]
    hits = [t for t in texts if any(p.search(t) for p in SUSPICIOUS)]
    return [Flag("SUSPICIOUS_TEXT", f"instruction-like text: {hits[0]!r}")] if hits else []


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def _match_po_line(po, line) -> tuple[object | None, str]:
    """The PO line an invoice line bills against: by the printed line number when there is one,
    else by description. The sample PDFs print no line numbers (measured 2026-11-14), so a real
    reading has none. Two PO lines with the same description are not guessed between."""
    if line.po_line is not None:
        found = next((p for p in po.lines if p.line == line.po_line), None)
        return found, "" if found else f"{po.number} has no line {line.po_line}"
    matches = [p for p in po.lines if _squash(p.description) == _squash(line.description)]
    if len(matches) == 1:
        return matches[0], ""
    if matches:
        return None, f"more than one line of {po.number} reads {line.description!r}; a person picks"
    return None, f"no line of {po.number} reads {line.description!r}"


def _po_checks(inv: Invoice, vendor: Vendor, erp: Company) -> list[Flag]:
    po = erp.po(inv.po)
    if po is None or po.vendor_id != vendor.id:
        return [Flag("PO_NOT_FOUND", f"purchase order {inv.po!r} is not open for {vendor.name}")]
    flags = []
    variance = Decimal(0)
    for line in inv.lines:
        po_line, why = _match_po_line(po, line)
        if po_line is None:
            flags.append(Flag("PO_NOT_FOUND", why))
            continue
        if line.unit_price > po_line.unit_price * (1 + PRICE_TOLERANCE):
            variance += (line.unit_price - po_line.unit_price) * line.quantity
        open_qty = erp.received(po.number, po_line.line) - erp.already_billed(po.number, po_line.line)
        if line.quantity > open_qty:
            over = line.quantity - open_qty
            flags.append(Flag("QTY_OVER_RECEIVED", f"{po.number} line {po_line.line}: billed {line.quantity}, open to bill {open_qty}", quantity=over))
    if variance:
        flags.insert(0, Flag("PRICE_VARIANCE", f"billed above {po.number} prices by more than {PRICE_TOLERANCE:.0%}", amount=money(variance)))
    return flags


def _recurring(inv: Invoice, vendor: Vendor, erp: Company) -> list[Flag]:
    history = [b for b in erp.bills_for(vendor.id) if b.date < inv.date][-RECURRING_WINDOW:]
    if len(history) < RECURRING_WINDOW:
        return []
    average = sum((b.total for b in history), Decimal(0)) / RECURRING_WINDOW
    if abs(inv.total - average) > average * RECURRING_TOLERANCE:
        return [Flag("UNUSUAL_AMOUNT", f"{inv.total} against a {RECURRING_WINDOW}-bill average of {money(average)}", amount=money(inv.total - average))]
    return []


def _account(inv: Invoice, vendor: Vendor | None, erp: Company) -> str | None:
    if vendor is None:
        return None
    po = erp.po(inv.po)
    if po is not None and po.vendor_id == vendor.id:
        matched = [_match_po_line(po, l)[0] for l in inv.lines]
        accounts = {p.account for p in matched if p is not None}
        if len(accounts) == 1:
            return accounts.pop()
        if accounts:
            return "split"
    return vendor.default_account


def check(inv: Invoice, erp: Company, document_text: str | None = None) -> Result:
    flags = _arithmetic(inv) + _suspicious(inv, document_text)
    vendor = erp.vendor_by_tax_id(inv.vendor_tax_id) or erp.vendor_by_name(inv.vendor_name)

    if vendor is None:
        flags.append(Flag("VENDOR_NOT_FOUND", f"{inv.vendor_name} ({inv.vendor_tax_id}) is not in the vendor master"))
    elif any(b.number == inv.number for b in erp.bills_for(vendor.id)):
        # A copy of a bill already paid: every other check would only repeat that.
        flags.append(Flag("DUPLICATE", f"{inv.number} was already paid"))
    else:
        if inv.remit_to != vendor.bank:
            flags.append(Flag("BANK_CHANGED", f"remit-to account ending {inv.remit_to.account_last4}, vendor master ending {vendor.bank.account_last4}"))
        if inv.kind == "credit_memo":
            if not inv.refers_to:
                flags.append(Flag("CREDIT_MEMO_UNREFERENCED", "a credit memo must name the invoice it credits"))
        elif vendor.uses_po:
            flags += _po_checks(inv, vendor, erp)
        elif vendor.recurring:
            flags += _recurring(inv, vendor, erp)

    account = _account(inv, vendor, erp)
    bank_changed = any(f.code == "BANK_CHANGED" for f in flags)
    controller = bank_changed or account == CAPITAL_ACCOUNT or abs(inv.total) >= CONTROLLER_FROM
    return Result(
        status="exception" if flags else "ready",
        flags=flags,
        approver="controller" if controller else "clerk",
        account=account,
        controller_only=bank_changed,
        phone_check=bank_changed,
    )
