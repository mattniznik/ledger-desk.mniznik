"""The suggested next step for a problem bill (playbook.py): what a finance team does about each kind
of problem, worked out by code from what the checks found, so the person gets a decision ready to
make instead of a red flag. Run on the 13 samples' ground truth, no model involved."""

import re
from pathlib import Path

import pytest

from ledger_desk.company import build_company
from ledger_desk.invoices import load_case
from ledger_desk.playbook import ORDER, STEPS, next_step
from ledger_desk.rules import check

ROOT = Path(__file__).resolve().parents[1]
COMPANY = build_company()


def flag(code, detail="", amount=None, quantity=None):
    return {"code": code, "detail": detail, "amount": amount, "quantity": quantity}


def facts(case_id):
    """The flags and the extraction the workflow keeps for a sample, from its ground truth."""
    inv = load_case(case_id).invoice
    flags = [flag(f.code, f.detail, None if f.amount is None else str(f.amount), None if f.quantity is None else str(f.quantity))
             for f in check(inv, COMPANY).flags]
    extraction = {"vendor_name": inv.vendor_name, "vendor_tax_id": inv.vendor_tax_id, "number": inv.number, "po": inv.po, "total": str(inv.total)}
    return flags, extraction


def step_for(case_id, **kw):
    return next_step(*facts(case_id), COMPANY, **kw)


@pytest.mark.parametrize("case_id, code, decision", [
    ("03", "PRICE_VARIANCE", "hold"),
    ("04", "TOTALS_MISMATCH", "hold"),
    ("06", "QTY_OVER_RECEIVED", "hold"),
    ("07", "DUPLICATE", "reject"),
    ("08", "BANK_CHANGED", "hold"),
    ("10", "UNUSUAL_AMOUNT", "hold"),
    ("11", "VENDOR_NOT_FOUND", "hold"),
    ("12", "SUSPICIOUS_TEXT", "hold"),
])
def test_each_problem_sample_gets_the_step_a_finance_team_would_take(case_id, code, decision):
    step = step_for(case_id)
    assert (step["code"], step["decision"]) == (code, decision)
    assert step["action"] and step["why"] and step["then"] and step["reason"]


def test_text_aimed_at_ai_is_held_and_confirmed_with_the_vendor():
    step = step_for("12")
    assert step["decision"] == "hold"
    assert "contact details on file" in step["then"]


@pytest.mark.parametrize("case_id", ["01", "02", "05", "09", "13"])
def test_a_clean_bill_has_no_suggested_step(case_id):
    assert step_for(case_id) is None


def test_a_bill_already_paid_names_the_paid_bill_by_its_own_date_and_amount():
    # Corrected 2026-11-14 after review: this test first pinned "already paid on Oct 14", but the
    # ERP keeps no payment date; Oct 14 is the bill's own date (invoices/07 notes "Original invoice
    # date: 2026-10-14"). The step must not tell the vendor a payment date nobody has.
    step = step_for("07")
    assert "dated Oct 14, 2026" in step["why"] and "$462.00" in step["why"]
    assert "paid on" not in step["why"] + step["then"] + step["reason"]
    assert step["reason"] == "Duplicate: DAI-5521 (dated Oct 14, 2026) already paid"


def test_an_overcharge_names_the_amount_and_the_purchase_order():
    step = step_for("03")
    assert "$200.00" in step["why"] and "PO-1124" in step["why"]
    assert "Packaging Supplier" in step["then"]


def test_billed_for_more_than_delivered_names_the_quantity():
    assert "20 more than" in step_for("06")["why"]


def test_a_bank_change_is_confirmed_on_the_number_on_file_never_one_from_the_bill():
    step = step_for("08")
    assert "number already in your vendor records" in step["then"]
    assert "controller" in step["then"]
    assert not re.search(r"\d{3}[-. ]\d{4}", step["then"] + step["why"])  # no phone number is invented


def test_an_amount_below_the_usual_bill_says_lower():
    step = next_step([flag("UNUSUAL_AMOUNT", amount="-300.00")], facts("10")[1], COMPANY)
    assert "lower" in step["action"] and "below" in step["why"] and "$300.00" in step["why"]


def test_with_several_problems_the_most_serious_decides_and_the_rest_are_listed():
    _, extraction = facts("03")
    step = next_step([flag("PRICE_VARIANCE", amount="200.00"), flag("BANK_CHANGED")], extraction, COMPANY)
    assert step["code"] == "BANK_CHANGED" and step["decision"] == "hold"
    assert len(step["also"]) == 1 and "$200.00" in step["also"][0]
    step = next_step([flag("BANK_CHANGED"), flag("DUPLICATE")], extraction, COMPANY)
    assert step["decision"] == "reject"


def test_a_code_the_playbook_does_not_know_is_held_not_dropped():
    step = next_step([flag("SOMETHING_NEW", "a check added later")], facts("03")[1], COMPANY)
    assert step["decision"] == "hold" and "a check added later" in step["why"]


def test_every_flag_code_the_checks_raise_has_a_step():
    raised = set()
    for f in (ROOT / "src" / "ledger_desk").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        raised |= set(re.findall(r'Flag\(\s*"([A-Z_]+)"', text)) | set(re.findall(r'"code":\s*"([A-Z_]+)"', text))
    assert len(raised) >= 11
    assert raised - set(STEPS) == set()
    assert set(ORDER) == set(STEPS)


def test_an_overcharge_the_vendor_already_credited_is_approved_against_the_credit():
    # sample 05, credit memo CM-PKG-0412 for -200.00, names PKG-20817 (sample 03)
    step = step_for("03", credits=[{"number": "CM-PKG-0412", "total": "-200.00"}])
    assert step["decision"] == "approve"
    assert "CM-PKG-0412" in step["why"] and "CM-PKG-0412" in step["reason"]
    assert "approve the credit too" in step["then"].lower()


def test_a_credit_smaller_than_the_overcharge_does_not_settle_it():
    step = step_for("03", credits=[{"number": "CM-1", "total": "-50.00"}])
    assert step["decision"] == "hold" and "CM-1" in step["why"]


def test_a_totals_problem_with_no_amount_never_says_zero_dollars():
    step = next_step([flag("TOTALS_MISMATCH", "line 1: 2000 x 0.12 is not 250.00")], facts("04")[1], COMPANY)
    assert "$0.00" not in step["why"] + step["reason"]
    assert "2000 x 0.12 is not 250.00" in step["why"]


def test_a_purchase_order_problem_says_what_does_not_match_and_never_that_the_order_is_missing():
    step = next_step([flag("PO_NOT_FOUND", "no line of PO-1124 reads 'Hot cups 12oz, white'")], facts("03")[1], COMPANY)
    assert "no line of PO-1124 reads" in step["why"]
    assert "not on file" not in step["why"]


def test_billed_for_more_than_delivered_is_not_told_to_wait_for_a_delivery_the_app_cannot_record():
    step = step_for("06")
    assert "delivered and not yet billed" in step["why"]
    assert "second bill" in step["why"]
    assert "record the delivery" not in step["then"] and "rest is delivered" not in step["action"]


def test_a_bank_change_the_vendor_did_not_ask_for_is_reported_and_the_genuine_bill_paid_not_rejected():
    step = step_for("08")
    assert "reject the bill" not in step["then"]
    assert "change nothing" in step["then"] and "genuine bill" in step["then"]
    assert "who confirmed it" in step["then"]


def test_a_bank_change_on_a_credit_memo_does_not_say_it_asks_to_be_paid():
    _, extraction = facts("05")
    step = next_step([flag("BANK_CHANGED")], extraction, COMPANY)
    assert "asks to be paid" not in step["why"] and "credit memo" in step["why"].lower()


def test_with_other_problems_open_the_step_says_they_come_first():
    step = next_step([flag("PRICE_VARIANCE", amount="200.00"), flag("BANK_CHANGED")], facts("03")[1], COMPANY)
    assert "other problems" in step["then"]


def test_without_a_drafted_email_the_step_does_not_mention_one():
    step = step_for("03", draft=False)
    assert "drafted" not in step["then"]
    assert "drafted email" in step_for("03")["then"]


def test_flagged_wording_is_read_before_anyone_assumes_it_was_aimed_at_an_ai():
    step = next_step([flag("SUSPICIOUS_TEXT", "instruction-like text: 'Please pay this invoice immediately.'")], facts("09")[1], COMPANY)
    assert "written to make an AI" not in step["why"]
    assert "Please pay this invoice immediately." in step["why"]
    assert "ordinary wording" in step["then"]


def test_a_new_vendor_is_checked_as_ordered_and_its_bank_confirmed_on_a_number_found_independently():
    step = step_for("11")
    assert "someone here ordered it" in step["then"]
    assert "not one from their paperwork" in step["then"]


def test_a_credit_settles_the_price_but_not_another_open_problem():
    step = next_step([flag("PRICE_VARIANCE", amount="200.00"), flag("QTY_OVER_RECEIVED", quantity="20")], facts("03")[1], COMPANY,
                     credits=[{"number": "CM-PKG-0412", "total": "-200.00"}])
    assert step["decision"] == "hold" and "other problems" in step["then"]
