"""Who may decide what on an invoice paused for approval.

A pure function, so the rules are tested on their own and the API only enforces what it returns:
- anyone with a role may reject or hold; approving needs authority;
- $5,000 and over, a capital purchase, or a bank change needs the controller (403 for a clerk);
  the $5,000 limit is checked here again from the total, not only taken from the pause;
- a bank change also needs the phone-check box: the vendor called on the number already on file
  (400 without it);
- approving with a flag open is an override and needs a typed reason (400 without one);
- an invoice with no proposed entry (no account) cannot be approved; a person codes it first.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .rules import CONTROLLER_FROM

ROLES = ("clerk", "controller")
DECISIONS = ("approve", "reject", "hold")


@dataclass(frozen=True)
class Refusal:
    status: int  # the HTTP status the API answers with
    message: str


def check_decision(pause: dict, role: str, decision: str, reason: str = "", phone_confirmed: bool = False) -> Refusal | None:
    if role not in ROLES:
        return Refusal(422, f"role must be one of {', '.join(ROLES)}")
    if decision not in DECISIONS:
        return Refusal(422, f"decision must be one of {', '.join(DECISIONS)}")
    if decision != "approve":
        return None
    total = abs(Decimal(str(pause.get("total") or "0")))
    needs_controller = pause.get("approver") == "controller" or pause.get("controller_only") or total >= CONTROLLER_FROM
    if needs_controller and role != "controller":
        why = "a bank change" if pause.get("controller_only") else f"${total:,.2f}" if total >= CONTROLLER_FROM else "this invoice"
        return Refusal(403, f"only the controller may approve {why}")
    if pause.get("controller_only") and not phone_confirmed:
        return Refusal(400, "a bank change needs the phone check: call the vendor on the number already on file, then tick the box")
    if pause.get("status") == "exception" and not (reason or "").strip():
        return Refusal(400, "approving with a flag open is an override: type the reason")
    if not (pause.get("proposal") or {}).get("lines"):
        return Refusal(400, "no entry to post: the invoice has no account yet; a person codes it first")
    return None
