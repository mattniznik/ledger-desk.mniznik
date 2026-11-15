"""The checking rules, run on each invoice's ground-truth fields with no model involved.

The first done-condition: all 13 sample invoices produce exactly their expected
flags. Each YAML file in invoices/ holds the invoice as printed and the expected result, and the
rules have to reproduce that result exactly: status, every flag with its amount, the approver and
the account."""

from decimal import Decimal

import pytest

from ledger_desk.company import build_company
from ledger_desk.invoices import Invoice, Line, load_all, load_case
from ledger_desk.rules import check

COMPANY = build_company()
CASES = load_all()


def flags_of(result):
    return {(f.code, f.amount, f.quantity) for f in result.flags}


def expected_flags(case):
    return {(f["code"], _dec(f.get("amount")), _dec(f.get("quantity"))) for f in case.expected.get("flags", [])}


def _dec(value):
    return None if value is None else Decimal(str(value))


def test_there_are_thirteen_sample_invoices():
    assert [c.id for c in CASES] == [f"{n:02d}" for n in range(1, 14)]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.slug)
def test_each_sample_invoice_gets_exactly_its_expected_result(case):
    result = check(case.invoice, COMPANY)
    assert result.status == case.expected["status"]
    assert flags_of(result) == expected_flags(case)
    assert result.approver == case.expected["approver"]
    assert result.account == case.expected.get("account")
    assert result.controller_only == case.expected.get("controller_only", False)


def test_01_clean_three_way_match_passes_and_goes_to_the_controller():
    result = check(load_case("01").invoice, COMPANY)
    assert (result.status, result.flags, result.approver) == ("ready", [], "controller")


def test_03_price_variance_is_exactly_200():
    result = check(load_case("03").invoice, COMPANY)
    assert flags_of(result) == {("PRICE_VARIANCE", Decimal("200.00"), None)}


def test_06_billed_twenty_more_than_received():
    result = check(load_case("06").invoice, COMPANY)
    assert flags_of(result) == {("QTY_OVER_RECEIVED", None, Decimal("20"))}


def test_07_an_invoice_already_paid_is_a_duplicate_and_nothing_else():
    result = check(load_case("07").invoice, COMPANY)
    assert [f.code for f in result.flags] == ["DUPLICATE"]


def test_08_a_bank_change_is_controller_only_with_a_phone_check():
    result = check(load_case("08").invoice, COMPANY)
    assert [f.code for f in result.flags] == ["BANK_CHANGED"]
    assert result.controller_only and result.phone_check and result.approver == "controller"


def test_09_a_normal_utility_bill_passes_with_the_utilities_account():
    result = check(load_case("09").invoice, COMPANY)
    assert (result.status, result.account) == ("ready", "6200")


def test_10_a_utility_bill_far_from_the_average_is_flagged():
    result = check(load_case("10").invoice, COMPANY)
    assert [f.code for f in result.flags] == ["UNUSUAL_AMOUNT"]


def test_12_an_instruction_in_the_invoice_text_is_flagged_not_obeyed():
    result = check(load_case("12").invoice, COMPANY)
    assert [f.code for f in result.flags] == ["SUSPICIOUS_TEXT"]
    assert result.status == "exception"


def _priced(unit_price: str) -> Invoice:
    """Invoice 01 re-priced: one line against a PO price of $310.00, everything else clean."""
    base = load_case("01").invoice
    line = base.lines[0]
    price = Decimal(unit_price)
    amount = (price * line.quantity).quantize(Decimal("0.01"))
    return Invoice(**{**base.__dict__, "lines": [Line(**{**line.__dict__, "unit_price": price, "amount": amount})], "subtotal": amount, "total": amount + base.tax})


@pytest.mark.parametrize(
    "unit_price, flagged",
    [("316.17", False), ("316.20", False), ("316.23", True)],  # +1.99%, +2.00%, +2.01% of $310.00
)
def test_the_price_tolerance_is_two_percent_inclusive(unit_price, flagged):
    result = check(_priced(unit_price), COMPANY)
    assert ("PRICE_VARIANCE" in [f.code for f in result.flags]) is flagged
