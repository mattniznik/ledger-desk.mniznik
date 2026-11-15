"""Matching an invoice line to its PO line when the invoice prints no line number.

Measured in the first real run (2026-11-14, n=13): the PDFs print no PO line numbers, so a real
reading has po_line null, and the rules, which matched by number only, flagged PO_NOT_FOUND on
01, 02, 06 and 13 (and 13's account fell back to the vendor's 6300 instead of the PO's 1500). The
ground-truth fake always filled the number in, which is how it went unseen. Lines now match by
number when there is one, else by description; never by "the PO has only one line".
"""

import dataclasses
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ledger_desk.company import POLine, PurchaseOrder, build_company
from ledger_desk.invoices import load_case
from ledger_desk.reading import read_invoice
from ledger_desk.rules import check
from ledger_desk.runner import ReplayModel

FIRST_RUN = Path(__file__).resolve().parents[1] / "replays" / "claude-opus-5-5-low"
OUT = Path(__file__).resolve().parents[1] / "out"


def without_line_numbers(inv, **line_changes):
    return dataclasses.replace(inv, lines=[dataclasses.replace(l, po_line=None, **line_changes) for l in inv.lines])


def outcome(result):
    return (result.status, sorted((f.code, f.amount, f.quantity) for f in result.flags), result.approver, result.account)


@pytest.fixture(scope="module")
def company():
    return build_company()


@pytest.mark.parametrize("case_id", ["01", "02", "03", "04", "06", "13"])
def test_an_invoice_without_line_numbers_gets_the_same_result(case_id, company):
    inv = load_case(case_id).invoice
    assert outcome(check(without_line_numbers(inv), company)) == outcome(check(inv, company))


def test_the_description_match_ignores_case_and_spacing(company):
    inv = load_case("01").invoice
    inv = without_line_numbers(inv, description="  GREEN coffee,   60 kg bag ")
    r = check(inv, company)
    assert r.status == "ready" and r.account == "1200"


def test_a_description_on_no_po_line_is_still_po_not_found(company):
    inv = without_line_numbers(load_case("01").invoice, description="Green coffee, 70 kg bag")
    r = check(inv, company)
    assert [f.code for f in r.flags] == ["PO_NOT_FOUND"]
    assert "Green coffee, 70 kg bag" in r.flags[0].detail


def test_a_printed_line_number_still_wins_over_the_description(company):
    # invoice 04's coffee bags ($0.85) printed against line 1 (lids, $0.12): the number is what the
    # PO is checked against, so the price is far off; matched by description it would be line 2, no variance
    inv = load_case("04").invoice
    moved = dataclasses.replace(inv, lines=[inv.lines[0], dataclasses.replace(inv.lines[1], po_line=1)])
    r = check(moved, company)
    assert "PRICE_VARIANCE" in [f.code for f in r.flags]


def test_two_po_lines_with_the_same_description_are_not_guessed(company):
    po = PurchaseOrder("PO-1199", "V01", date(2026, 11, 2), (POLine(1, "Green coffee, 60 kg bag", Decimal(10), Decimal("310.00"), "1200"), POLine(2, "Green coffee, 60 kg bag", Decimal(10), Decimal("300.00"), "1200")))
    twin = dataclasses.replace(company, purchase_orders=[*company.purchase_orders, po])
    inv = without_line_numbers(dataclasses.replace(load_case("01").invoice, po="PO-1199"))
    r = check(inv, twin)
    assert [f.code for f in r.flags] == ["PO_NOT_FOUND"] and "more than one" in r.flags[0].detail


@pytest.mark.parametrize("case_id", ["01", "06", "13"])
def test_the_first_real_runs_readings_now_match_their_po(case_id, company):
    recorded = json.loads((FIRST_RUN / f"{case_id}.json").read_text(encoding="utf-8"))
    assert all(l["po_line"] is None for l in recorded["outcome"]["extraction"]["lines"])  # the fixture is what it says
    doc = next(OUT.glob(f"{load_case(case_id).slug}.*"))
    result = read_invoice(doc, ReplayModel(recorded["replies"][:1]))
    r = check(result.invoice, company)
    exp = load_case(case_id).expected
    assert r.status == exp["status"] and [f.code for f in r.flags] == [f["code"] for f in exp.get("flags", [])]
    assert r.account == exp["account"]
