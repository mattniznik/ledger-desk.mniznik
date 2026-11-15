"""The eval results through the app API, for the Evals page: one results file
per version and model. Public: no session needed, nothing private in them.
A results name is checked against a strict pattern, so the endpoint cannot be walked out of the
results folder.
"""

import json

import pytest
from fastapi.testclient import TestClient

from ledger_desk.api import create_api

SUMMARY = {
    "cases": 2, "end_result": {"exact": 1, "status_ok": 2, "failed": ["v34"], "known_limits": ["v34"]},
    "flags": {"SUSPICIOUS_TEXT": {"tp": 1, "fp": 0, "fn": 1, "precision": 1.0, "recall": 0.5}},
    "reading": {"pdf": {"cases": 2, "fields": 20, "fields_correct": 20}, "photo": {"cases": 0, "fields": 0, "fields_correct": 0}},
    "account": {"graded": 2, "top1": 2}, "safety": {"graded": 2, "passed": 2},
    "cost": {"usd": 0.12, "per_invoice_usd": 0.06}, "time": {"seconds": 30.0, "per_invoice_seconds": 15.0}, "errors": [],
}


@pytest.fixture
def results(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    for name, model, tier in [("m5a-subscription-claude-opus-5-5", "subscription-claude-opus-5-5", "standard"), ("m5a-scripted", "scripted", "standard"), ("m5a-hard-subscription-claude-opus-5-5", "subscription-claude-opus-5-5", "hard")]:
        cases = [{"id": "12", "exact": True, "known_limit": False}, {"id": "v34", "exact": False, "known_limit": True}]
        (d / f"{name}.json").write_text(json.dumps({"version": "m5a", "tier": tier, "model": model, "date": "2026-11-14", "summary": SUMMARY, "cases": cases}), encoding="utf-8")
    return d


@pytest.fixture
def client(erp_db, results, tmp_path):
    return TestClient(create_api(erp_db, docs_dir=tmp_path / "docs", results_dir=results))


def test_the_list_has_every_run_with_its_summary_and_says_what_a_scripted_run_proves(client):
    runs = client.get("/evals").json()["runs"]
    assert [r["name"] for r in runs] == ["m5a-hard-subscription-claude-opus-5-5", "m5a-scripted", "m5a-subscription-claude-opus-5-5"]
    real = runs[2]
    assert real["model"] == "subscription-claude-opus-5-5" and real["tier"] == "standard" and real["summary"]["end_result"]["exact"] == 1
    assert "cases" not in real  # the list stays small; per-case detail is its own call
    assert runs[1]["proves"] == "the graders and the rules, not a model" and real["proves"] == "the model"


def test_one_run_comes_with_its_cases(client):
    r = client.get("/evals/m5a-subscription-claude-opus-5-5").json()
    assert [c["id"] for c in r["cases"]] == ["12", "v34"] and r["cases"][1]["known_limit"] is True


@pytest.mark.parametrize("name", ["nope", "..%2Fsecrets", "m5a-scripted.json", "a b", "..%5Cresults%5Cm5a-scripted"])  # the last walks up and back down with a backslash
def test_an_unknown_or_unsafe_name_is_a_404(client, name):
    assert client.get(f"/evals/{name}").status_code == 404


def test_no_results_yet_is_an_empty_list_not_an_error(erp_db, tmp_path):
    empty = tmp_path / "none"
    c = TestClient(create_api(erp_db, docs_dir=tmp_path / "docs", results_dir=empty))
    assert c.get("/evals").json() == {"runs": []}
