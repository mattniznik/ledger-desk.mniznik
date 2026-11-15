"""Amounts as the model really returns them.

The first real run (2026-11-14, Claude Opus 5.5 via the subscription, n=13 reads) returned plain
decimals for 11 invoices and the printed form for 2: invoice 03 as "$0.42", "$2,100.00" and a
quantity of "5,000"; invoice 04 the same way. `Decimal` rejects those, so both went to manual
entry. US-printed amounts are now read; anything else is still refused, never guessed.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from ledger_desk.company import build_company
from ledger_desk.invoices import load_case
from ledger_desk.reading import Extraction, printed_number, read_invoice
from ledger_desk.rules import check
from ledger_desk.runner import ReplayModel

FIRST_RUN = Path(__file__).resolve().parents[1] / "replays" / "claude-opus-5-5-low"
OUT = Path(__file__).resolve().parents[1] / "out"


@pytest.mark.parametrize(
    "text, value",
    [("$0.42", "0.42"), ("$2,100.00", "2100.00"), ("5,000", "5000"), ("-$200.00", "-200.00"), ("$-200.00", "-200.00"), ("6200.00", "6200.00"), ("1,234,567.89", "1234567.89"), (" 189.00 ", "189.00")],
)
def test_us_printed_amounts_are_read(text, value):
    assert printed_number(text) == Decimal(value)


@pytest.mark.parametrize("text", ["1.234,56", "about 2100", "5,00", "", "$", "--5", "-$-5", "(200.00)", "2,100.00 USD", "12,34"])
def test_anything_else_is_refused(text):
    with pytest.raises(ValueError):
        printed_number(text)


def _first_run_reading(case_id):
    recorded = json.loads((FIRST_RUN / f"{case_id}.json").read_text(encoding="utf-8"))
    first_reply = recorded["replies"][0]
    assert first_reply["task"] == "read" and "$" in first_reply["reply"]["text"]  # the fixture is what it says
    doc = next(OUT.glob(f"{load_case(case_id).slug}.*"))
    return read_invoice(doc, ReplayModel([first_reply]))


@pytest.mark.parametrize("case_id, total", [("03", "2100.00"), ("04", "755.00")])
def test_the_first_real_runs_printed_readings_are_now_read(case_id, total):
    result = _first_run_reading(case_id)
    assert result.status == "read", result.reason
    assert result.invoice.total == Decimal(total)
    assert result.source_checks["total"] == "ok"


@pytest.mark.parametrize("case_id, flag", [("03", "PRICE_VARIANCE"), ("04", "TOTALS_MISMATCH")])
def test_the_first_real_runs_printed_readings_get_exactly_their_expected_flag(case_id, flag):
    result = _first_run_reading(case_id)
    assert [f.code for f in check(result.invoice, build_company()).flags] == [flag]


def test_the_extraction_kept_downstream_is_plain_decimals():
    # the workflow keeps the extraction in its state and the proposal reads its total from there
    recorded = json.loads((FIRST_RUN / "03.json").read_text(encoding="utf-8"))
    doc = next(OUT.glob(f"{load_case('03').slug}.*"))
    e = read_invoice(doc, ReplayModel(recorded["replies"][:1])).extraction
    assert (e.total, e.subtotal, e.tax) == ("2100.00", "2100.00", "0.00")
    assert (e.lines[0].quantity, e.lines[0].unit_price, e.lines[0].amount) == ("5000", "0.42", "2100.00")
    assert e.sources["total"].endswith("$2,100.00")  # the printed form stays in the source text


def test_the_schema_asks_for_plain_decimals():
    schema = Extraction.model_json_schema()
    assert "plain decimal" in schema["properties"]["total"]["description"]
    assert "plain decimal" in schema["$defs"]["ExtractedLine"]["properties"]["unit_price"]["description"]
