"""What a finance team does about each kind of problem bill: the suggested next step.

The checks (rules.py) say what is wrong; this says what to do about it, in the words an
accounts-payable desk uses, so the person gets a decision ready to make instead of a red flag:
hold for a corrected bill, reject a copy already paid, hold a bank change until the vendor confirms
it on the phone number already on file, approve an overcharge the vendor has already credited.

A pure function over what the checks found, the company's records and the credit memos waiting in
the visitor's queue. No model call: a recorded run replays its model calls by task order, so a new
call would break every recording, and the app's rule is that code makes every decision about money
(docs/decisions/0002, 0007). Claude's part stays the explanation and the email draft.

It only suggests. The person still presses the button, and the API still checks the decision
(authority.check_decision): a hold or a reject needs no authority; the one approval it can suggest
(an overcharge settled by a credit) still needs the approver's authority and carries its reason.

Wording rules learned in review (2026-11-14): the ERP keeps a paid bill's own date, not the day it
was paid; the quantity check compares with what was delivered and not yet billed; PO_NOT_FOUND also
means a line that matches no line of the order; the instruction check is a phrase list, so it
cannot know intent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable

from .company import Bill, Company


@dataclass(frozen=True)
class Facts:
    vendor: str
    number: str
    po: str | None
    total: Decimal
    detail: str
    amount: Decimal | None
    quantity: Decimal | None
    paid: Bill | None  # for a copy of a bill already paid: the paid one, from the company's records
    credits: tuple = field(default_factory=tuple)  # credit memos in the queue that name this bill: (number, amount)
    draft: bool = True  # whether the assistant drafted an email to the vendor


def _usd(value: Decimal | None) -> str:
    return f"${abs(value or Decimal(0)):,.2f}"


def _day(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _qty(value: Decimal | None) -> str:
    return f"{(value or Decimal(0)).normalize():f}"


def _ask(f: Facts) -> str:
    return f"Send {f.vendor} the drafted email asking" if f.draft else f"Ask {f.vendor}"


def _step(decision: str, action: str, why: str, then: str, reason: str) -> dict:
    return {"decision": decision, "action": action, "why": why, "then": then, "reason": reason}


def _duplicate(f: Facts) -> dict:
    then = f"Nothing to pay. Let {f.vendor} know {f.number} has already been paid, in case their records still show it open."
    if f.paid:
        when = _day(f.paid.date)
        why = f"{f.number} (dated {when}, {_usd(f.paid.total)}) is already among the paid bills. Paying this copy would send {f.vendor} the same money twice."
        return _step("reject", "Reject as already paid", why, then, f"Duplicate: {f.number} (dated {when}) already paid")
    why = f"{f.number} is already among the paid bills. Paying this copy would send {f.vendor} the same money twice."
    return _step("reject", "Reject as already paid", why, then, f"Duplicate: {f.number} already paid")


def _bank_changed(f: Facts) -> dict:
    what = "The credit memo shows a different bank account from the one on file." if f.total < 0 else \
        "The bill asks to be paid into a different bank account from the one on file."
    return _step(
        "hold", "Hold until the new bank account is confirmed",
        f"{what} A fake bank-change request is a common way fraudsters get paid instead of the vendor, and money sent to the wrong "
        "account is hard to get back.",
        f"The controller calls {f.vendor} on the number already in your vendor records, never one from the bill or the email. If they "
        "confirm the change, approve with the phone check ticked and a note of who confirmed it. If they did not ask for it, change "
        f"nothing, tell whoever looks after security, and ask {f.vendor} for the genuine bill, which pays to the account on file.",
        "Bank change: on hold until confirmed by phone on the number on file",
    )


def _vendor_not_found(f: Facts) -> dict:
    return _step(
        "hold", "Hold until the vendor is set up",
        f"{f.vendor} is not set up as a vendor yet, so nobody has checked who they are or where their money should go.",
        f"Check that someone here ordered it. Ask {f.vendor} for a W-9 and their bank details, and confirm the bank details by calling a "
        "number you found yourself, not one from their paperwork. Then set them up and code this bill.",
        f"New vendor: on hold until {f.vendor} is set up",
    )


def _suspicious_text(f: Facts) -> dict:
    quote = f.detail.split(": ", 1)[1] if f.detail.startswith("instruction-like text: ") else f.detail
    return _step(
        "hold", "Hold and read the flagged text",
        f"The bill has wording that reads like an instruction to an automated system: {quote}. It was treated as data and changed "
        "nothing. The check looks for phrases, so ordinary wording can trip it too.",
        "Read it. If it is ordinary wording, approve it with that as the reason. If it is aimed at an AI, confirm the bill with "
        f"{f.vendor} using the contact details on file and tell whoever looks after security.",
        "Instruction-like text on the bill: on hold until read",
    )


def _source_not_found(f: Facts) -> dict:
    return _step(
        "hold", "Hold and check the document by hand",
        "A value read from the bill could not be found on the document, so the reading may be wrong.",
        "Compare what was read with the document. If it is right, approve it with that as the reason.",
        "Reading not confirmed on the document: on hold for a check by hand",
    )


def _totals_mismatch(f: Facts) -> dict:
    if f.amount:
        why = f"The printed total is {_usd(f.amount)} different from what its lines add up to."
        reason = f"Total does not add up ({_usd(f.amount)} off): asked {f.vendor} for a corrected bill"
    else:
        why = f"The bill's arithmetic does not add up: {f.detail}."
        reason = f"Arithmetic does not add up: asked {f.vendor} for a corrected bill"
    return _step(
        "hold", "Hold for a corrected bill", f"{why} A bill that does not add up is not paid as printed.",
        f"{_ask(f)} for a corrected bill, and pay that one.", reason,
    )


def _price_variance(f: Facts) -> dict:
    po = f.po or "the purchase order"
    covering = next(((n, a) for n, a in f.credits if a >= (f.amount or Decimal(0))), None)
    if covering:
        n, a = covering
        return _step(
            "approve", f"Approve against credit {n}",
            f"Billed {_usd(f.amount)} above the prices agreed on {po}, and {f.vendor} has already sent credit memo {n} for {_usd(a)} "
            "that names this bill, which brings it back to the agreed price.",
            "Approve this bill with the credit as the reason, and approve the credit too: together they pay the agreed price. No email "
            "is needed; the assistant searched the company's books, where the credit is not booked yet, so it did not see it.",
            f"Overcharge of {_usd(f.amount)} settled by credit memo {n}",
        )
    partial = f" Credit memo {f.credits[0][0]} for {_usd(f.credits[0][1])} names this bill but does not cover it all." if f.credits else ""
    return _step(
        "hold", "Hold for a corrected bill",
        f"Billed {_usd(f.amount)} above the prices agreed on {po}.{partial}",
        f"{_ask(f)} for a bill at the agreed prices, or a credit for the difference. If the buyer agreed the new price, approve it with "
        "that as the reason.",
        f"Price above {po}: asked {f.vendor} for a corrected bill ({_usd(f.amount)} over)",
    )


def _qty_over_received(f: Facts) -> dict:
    po = f.po or "the purchase order"
    ask = _ask(f)
    return _step(
        "hold", "Hold for a corrected bill",
        f"Billed for {_qty(f.quantity)} more than has been delivered and not yet billed on {po}. Either part of the order has not "
        "arrived, or this is a second bill for goods already billed.",
        f"Pay only for what was delivered: {ask[0].lower() + ask[1:]} for a corrected bill or a credit for the {_qty(f.quantity)} extra.",
        f"Billed {_qty(f.quantity)} more than delivered and not yet billed on {po}: asked {f.vendor} for a corrected bill",
    )


def _po_not_found(f: Facts) -> dict:
    return _step(
        "hold", "Hold until it matches a purchase order",
        f"It does not match a purchase order on file: {f.detail}. So nobody has agreed this price or quantity.",
        "Ask the person who ordered it which purchase order and line it belongs to, or for written approval to pay it without one.",
        "Does not match a purchase order on file: on hold",
    )


def _credit_unreferenced(f: Facts) -> dict:
    return _step(
        "hold", "Hold until the vendor says which bill it is for",
        "A credit that does not name its bill cannot be matched to what is owed, so it could be applied to the wrong bill or twice.",
        f"Ask {f.vendor} which bill this credit reduces, then approve it.",
        f"Credit memo with no bill named: asked {f.vendor} which bill it is for",
    )


def _unusual_amount(f: Facts) -> dict:
    up = (f.amount or Decimal(0)) >= 0
    return _step(
        "hold", f"Hold and ask why it is {'higher' if up else 'lower'}",
        f"{_usd(f.amount)} {'above' if up else 'below'} the usual bill from {f.vendor}.",
        "Check with whoever would know (for a utility, the meter reading). If there is a good reason, approve it with that as the reason.",
        f"Unusual amount ({_usd(f.amount)} {'above' if up else 'below'} the usual bill): on hold until explained",
    )


STEPS: dict[str, Callable[[Facts], dict]] = {
    "DUPLICATE": _duplicate,
    "BANK_CHANGED": _bank_changed,
    "VENDOR_NOT_FOUND": _vendor_not_found,
    "SUSPICIOUS_TEXT": _suspicious_text,
    "SOURCE_NOT_FOUND": _source_not_found,
    "TOTALS_MISMATCH": _totals_mismatch,
    "PRICE_VARIANCE": _price_variance,
    "QTY_OVER_RECEIVED": _qty_over_received,
    "PO_NOT_FOUND": _po_not_found,
    "CREDIT_MEMO_UNREFERENCED": _credit_unreferenced,
    "UNUSUAL_AMOUNT": _unusual_amount,
}
# With several problems the most serious decides: money already paid, then where the money goes,
# then who the vendor is, then whether the bill can be trusted at all, then the amounts.
ORDER = list(STEPS)


def _unknown(code: str, f: Facts) -> dict:
    return _step("hold", "Hold and look into it", f.detail or code, "Look into it before paying.", f"{code}: on hold")


def _dec(value) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def next_step(flags: list[dict], extraction: dict, company: Company, credits=(), draft: bool = True) -> dict | None:
    """The suggested step for a bill with these flags, or None for a clean bill.

    credits: credit memos in the visitor's queue that name this bill and were not rejected, as
    {"number", "total"}; draft: whether the assistant drafted an email to the vendor."""
    if not flags:
        return None
    rank = {code: i for i, code in enumerate(ORDER)}
    ordered = sorted(flags, key=lambda fl: rank.get(fl["code"], len(ORDER)))
    vendor = company.vendor_by_tax_id(extraction.get("vendor_tax_id")) or company.vendor_by_name(extraction.get("vendor_name") or "")
    number = extraction.get("number") or ""
    paid = next((b for b in company.bills_for(vendor.id) if b.number == number), None) if vendor else None
    queued_credits = tuple((c["number"], abs(Decimal(str(c["total"])))) for c in credits)

    def build(fl: dict) -> dict:
        f = Facts(vendor=extraction.get("vendor_name") or "the vendor", number=number, po=extraction.get("po"),
                  total=_dec(extraction.get("total")) or Decimal(0), detail=fl.get("detail") or "",
                  amount=_dec(fl.get("amount")), quantity=_dec(fl.get("quantity")), paid=paid, credits=queued_credits, draft=draft)
        make = STEPS.get(fl["code"])
        return make(f) if make else _unknown(fl["code"], f)

    first = build(ordered[0])
    also = [build(fl)["why"] for fl in ordered[1:]]
    if also and first["decision"] != "reject":
        first["then"] += " The other problems below need sorting out before it is approved."
        if first["decision"] == "approve":  # a credit settles the price, not the other problems
            first = {**first, "decision": "hold", "action": "Hold: other problems are open"}
    return {"code": ordered[0]["code"], **first, "also": also}
