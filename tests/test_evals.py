"""The eval harness and its graders.

Each grader passes a known-good result and fails a known-bad one; the runner's
total equals the number of cases. Graded by code against the YAML ground truth; no LLM judge.
Run here with the scripted perfect reader, which proves the graders, not any model.
"""

import json

import pytest

from ledger_desk.evals import (
    flag_scores,
    grade_account,
    grade_reading,
    grade_result,
    grade_safety,
    run_eval,
)
from ledger_desk.invoices import load_case, load_eval_set
from ledger_desk.scripted import perfect_reading


# --- reading ----------------------------------------------------------------------------------

def test_reading_grader_passes_a_perfect_reading_and_names_the_misread_field():
    case = load_case("03")
    good = grade_reading(case, perfect_reading(case))
    assert good and all(good.values())
    assert {"number", "date", "po", "total", "subtotal", "tax", "line1.quantity", "line1.unit_price", "remit_account_last4"} <= set(good)
    bad = grade_reading(case, perfect_reading(case, total="2010.00"))
    assert [k for k, ok in bad.items() if not ok] == ["total"]


def test_reading_grader_compares_amounts_to_the_cent_not_as_text():
    case = load_case("03")
    same_value = perfect_reading(case, total="2100.0", subtotal="2100")
    assert all(grade_reading(case, same_value).values())


# --- end result ---------------------------------------------------------------------------------

def outcome(status, flags, approver="clerk", account=None, suggestion=None):
    return {"status": status, "flags": [{"code": c, "amount": a, "quantity": None, "detail": ""} for c, a in flags], "approver": approver, "account": account, "account_suggestion": suggestion}


def test_result_grader_passes_the_expected_result_and_fails_a_missed_or_extra_flag():
    case = load_case("03")  # PRICE_VARIANCE 200.00, clerk, 1210
    good = grade_result(case, outcome("exception", [("PRICE_VARIANCE", "200.00")], account="1210"))
    assert good["exact"] is True and good["tp"] == {"PRICE_VARIANCE": 1} and not good["fp"] and not good["fn"]
    missed = grade_result(case, outcome("ready", [], account="1210"))
    assert missed["exact"] is False and missed["fn"] == {"PRICE_VARIANCE": 1}
    extra = grade_result(case, outcome("exception", [("PRICE_VARIANCE", "200.00"), ("SOURCE_NOT_FOUND", None)], account="1210"))
    assert extra["exact"] is False and extra["fp"] == {"SOURCE_NOT_FOUND": 1}


def test_precision_and_recall_per_flag_type():
    graded = [
        {"tp": {"A": 1}, "fp": {}, "fn": {}},
        {"tp": {"A": 1}, "fp": {"A": 1}, "fn": {}},
        {"tp": {}, "fp": {}, "fn": {"A": 1, "B": 1}},
    ]
    s = flag_scores(graded)
    assert s["A"] == {"tp": 2, "fp": 1, "fn": 1, "precision": pytest.approx(2 / 3), "recall": pytest.approx(2 / 3)}
    assert s["B"]["recall"] == 0.0 and s["B"]["precision"] is None  # never predicted: no precision to speak of


# --- account ----------------------------------------------------------------------------------

def test_account_grader_scores_the_models_pick_on_bills_without_a_po():
    case = load_case("09")  # utility, no PO, 6200
    assert grade_account(case, outcome("ready", [], suggestion={"suggested": "6200"})) is True
    assert grade_account(case, outcome("ready", [], suggestion={"suggested": "1500"})) is False
    assert grade_account(load_case("01"), outcome("ready", [])) is None  # has a PO: not graded here
    assert grade_account(load_case("11"), outcome("exception", [], suggestion={"suggested": "6400"})) is None  # no expected account


# --- safety -----------------------------------------------------------------------------------

def test_safety_grader_fails_anything_posted_without_a_signed_approval():
    case = load_case("12")
    assert grade_safety(case, {"status": "exception"}, entries_posted=0) is True
    assert grade_safety(case, {"status": "posted"}, entries_posted=1) is False
    assert grade_safety(case, {"status": "exception"}, entries_posted=1) is False


# --- the harness --------------------------------------------------------------------------------

def test_the_runner_grades_every_case_it_is_given_and_writes_a_results_file(erp_db, tmp_path):
    cases = [c for c in load_eval_set() if c.id in ("01", "02", "08", "09", "12", "v24", "v34")]
    results = run_eval(cases, "scripted", erp_db, docs_dir=tmp_path / "docs", out_dir=tmp_path / "results", version="test")
    s = results["summary"]
    assert s["cases"] == len(cases) == 7
    assert s["end_result"]["exact"] == 6 and s["end_result"]["failed"] == ["v34"]  # the known limit, and only it
    assert s["end_result"]["known_limits"] == ["v34"]
    assert s["reading"]["pdf"]["cases"] == 6 and s["reading"]["photo"]["cases"] == 1
    assert s["reading"]["pdf"]["fields_correct"] == s["reading"]["pdf"]["fields"]  # the perfect reader
    assert s["account"]["graded"] == 5 and s["account"]["top1"] == 5  # 08, 09, 12, v24, v34 have no PO
    assert s["safety"] == {"graded": 7, "passed": 7}
    saved = json.loads((tmp_path / "results" / "test-scripted.json").read_text(encoding="utf-8"))
    assert saved["model"] == "scripted" and len(saved["cases"]) == 7 and saved["summary"]["cases"] == 7
