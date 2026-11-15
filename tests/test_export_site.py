"""The page's numbers come from scripts/export_site.py, never typed in. These pin its pure parts on the real
eval results, recorded runs and decision records, and its refusal to export from a failing test suite."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("export_site", ROOT / "scripts" / "export_site.py")
export_site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_site)


def test_pytest_totals_are_read_from_its_last_line():
    assert export_site.count_pytest("....\n336 passed in 25.64s\n") == {"tests": 336, "passed": 336, "failed": 0}
    assert export_site.count_pytest("1 failed, 335 passed, 2 errors in 9.1s") == {"tests": 338, "passed": 335, "failed": 3}
    with pytest.raises(ValueError):
        export_site.count_pytest("collected 0 items")


def test_vitest_totals_are_read_from_its_tests_line():
    assert export_site.count_vitest(" Test Files  8 passed (8)\n      Tests  58 passed (58)\n") == {"tests": 58, "passed": 58, "failed": 0, "files": 8}
    assert export_site.count_vitest("      Tests  2 failed | 56 passed (58)") == {"tests": 58, "passed": 56, "failed": 2, "files": 0}
    with pytest.raises(ValueError):
        export_site.count_vitest("No test files found")


def test_it_refuses_to_export_from_a_red_or_empty_suite():
    green = {"tests": 10, "passed": 10, "failed": 0}
    export_site.require_green({"python": green, "web": green})
    with pytest.raises(SystemExit):
        export_site.require_green({"python": green, "web": {"tests": 10, "passed": 9, "failed": 1}})
    with pytest.raises(SystemExit):
        export_site.require_green({"python": {"tests": 0, "passed": 0, "failed": 0}, "web": green})


def test_eval_runs_carry_what_the_page_shows_from_the_results_files():
    runs = export_site.eval_runs(ROOT / "evals" / "results")
    opus = next(r for r in runs if r["model"] == "subscription-claude-opus-5-5" and r["tier"] == "standard")
    assert (opus["cases"], opus["end_result"], opus["fields_correct"], opus["fields"]) == (50, 49, 504, 504)
    assert (opus["pdf_fields"], opus["photo_fields"], opus["account_top1"], opus["account_graded"]) == (424, 80, 21, 21)
    assert opus["safe"] == 50 and opus["per_invoice_usd"] == pytest.approx(0.0713, abs=1e-4)
    assert opus["per_invoice_seconds"] == pytest.approx(15.79)
    hard = next(r for r in runs if r["model"] == "subscription-claude-opus-5-5" and r["tier"] == "hard")
    assert (hard["cases"], hard["end_result"], hard["fields_correct"]) == (10, 10, 170)
    assert all(r["proves"] == "the graders and the rules, not a model" for r in runs if r["model"] == "scripted")


def test_recorded_runs_are_summed_with_their_n():
    rec = export_site.recorded_runs(ROOT / "replays" / "claude-opus-5-5-low-run2")
    assert (rec["n"], rec["matched"], rec["model_calls"]) == (13, 13, 40)
    assert rec["cost_usd"]["total"] == pytest.approx(0.9876, abs=1e-4)
    assert rec["seconds"]["total"] == pytest.approx(207.8, abs=0.1) and rec["seconds"]["median"] == pytest.approx(18.76)
    assert len(rec["runs"]) == 13 and rec["runs"][0]["sample"] == "01"


def test_decision_records_are_listed_from_their_index():
    decisions = export_site.decisions(ROOT / "docs" / "decisions" / "README.md")
    assert len(decisions) == 10  # 0010 added 2026-11-14 (browser tests against the real API)
    assert decisions[0] == {"number": "0001", "title": "One bill's run is a LangGraph graph that pauses for the person's decision",
                            "file": "docs/decisions/0001-langgraph-workflow-with-an-approval-pause.md"}


def test_the_approval_limits_shown_on_the_page_come_from_the_rules():
    from ledger_desk.agent import MAX_TOOL_CALLS
    from ledger_desk.rules import CONTROLLER_FROM, PRICE_TOLERANCE

    p = export_site.policies()
    # max_lookups added with the system map, which states the agent's limit
    assert p == {"controller_from": float(CONTROLLER_FROM), "price_tolerance_percent": float(PRICE_TOLERANCE * 100), "max_lookups": MAX_TOOL_CALLS}
    assert p["controller_from"] == 5000.0 and p["price_tolerance_percent"] == 2.0


GREEN_PY = "342 passed in 20.1s"
GREEN_WEB = "      Tests  59 passed (59)"


def test_the_suites_run_against_the_new_data_and_a_red_run_puts_the_old_file_back(tmp_path):
    out = tmp_path / "site-data.json"
    out.write_text('{"old": true}\n', encoding="utf-8")
    seen = []

    def red(_):
        seen.append(out.read_text(encoding="utf-8"))  # what the suites ran against
        return {"python": (1, "1 failed, 341 passed in 20.1s"), "web": (0, GREEN_WEB)}

    with pytest.raises(SystemExit):
        export_site.export(out, red)
    assert '"policies"' in seen[0]  # the new data was in place while the tests ran
    assert out.read_text(encoding="utf-8") == '{"old": true}\n'  # and the old file is back


def test_a_green_run_writes_the_fresh_counts(tmp_path):
    out = tmp_path / "site-data.json"
    data = export_site.export(out, lambda _: {"python": (0, GREEN_PY), "web": (0, GREEN_WEB)})
    py_files = len(list((ROOT / "tests").glob("test_*.py")))
    assert data["tests"] == {"python": {"tests": 342, "passed": 342, "failed": 0, "files": py_files}, "web": {"tests": 59, "passed": 59, "failed": 0, "files": 0}}
    assert '"passed": 342' in out.read_text(encoding="utf-8")


def test_each_recorded_run_names_its_bill_what_was_found_and_the_steps_it_took():
    rec = export_site.recorded_runs(ROOT / "replays" / "claude-opus-5-5-low-run2")
    run03 = next(r for r in rec["runs"] if r["sample"] == "03")
    assert (run03["vendor"], run03["number"], run03["total"], run03["status"]) == ("Packaging Supplier", "PKG-20817", "2100.00", "exception")
    assert run03["flags"] == [{"code": "PRICE_VARIANCE", "amount": "200.00", "detail": "billed above PO-1124 prices by more than 2%"}]
    assert run03["explanation"].startswith("Invoice PKG-20817 from Packaging Supplier")
    assert [s["task"] for s in run03["steps"]] == ["read", "investigate", "investigate", "investigate"]
    assert run03["steps"][1]["tools"] == ["get_purchase_order", "get_receipts", "get_vendor"]
    assert rec["cost_usd"]["min"] <= rec["cost_usd"]["median"] <= rec["cost_usd"]["max"]
    assert rec["seconds"]["min"] <= rec["seconds"]["max"]


def test_the_model_is_named_for_people():
    assert export_site.model_of(ROOT / "replays" / "claude-opus-5-5-low-run2") == {"id": "claude-opus-5-5", "name": "Claude Opus 5.5"}


def test_the_test_files_are_counted_too():
    assert export_site.count_vitest(" Test Files  12 passed (12)\n      Tests  79 passed (79)\n")["files"] == 12
    assert export_site.count_pytest("348 passed in 20s")["tests"] == 348


def test_how_it_was_built_reads_every_number_from_the_data():
    data = {"tests": {"python": {"tests": 348, "files": 30}, "web": {"tests": 79, "files": 12}},
            "recorded": {"n": 13, "matched": 13, "cost_usd": {"total": 0.9876, "min": 0.0447, "max": 0.1432}},
            "checks": 11}
    steps = export_site.built_steps(data, repo=None)
    assert [s["title"] for s in steps] == ["Plan from the provider's documentation", "Write the test, watch it fail", "Change the code",
                                           "Measure on real runs", "Independent review", "Check it in a browser"]
    text = " ".join(s["fact"] for s in steps)
    for n in ("427 tests", "42 files", "11 checks", "13 real runs", "$0.99", "$0.0447", "$0.1432", "13 of 13"):
        assert n in text, n
    assert all(s["url"] is None for s in steps)  # no links until the repository has a public home


def test_each_recorded_run_carries_its_source_checks_and_its_suggested_next_step():
    rec = export_site.recorded_runs(ROOT / "replays" / "claude-opus-5-5-low-run2")
    over = next(r for r in rec["runs"] if r["sample"] == "03")
    assert over["source_checks"] == {"ok": 6, "missing": 0, "not_checked": 0}
    assert over["next_step"] == {"code": "PRICE_VARIANCE", "decision": "hold", "action": "Hold for a corrected bill"}
    assert next(r for r in rec["runs"] if r["sample"] == "09")["next_step"] is None


def test_the_recorded_runs_lookups_come_from_replaying_them_through_the_code():
    lookups = export_site.replayed_lookups(ROOT / "replays" / "claude-opus-5-5-low-run2", "ledger_desk_test_export", samples=["03", "09"])
    assert [l["tool"] for l in lookups["03"]] == ["get_purchase_order", "get_receipts", "get_vendor", "draft_vendor_email"]
    assert lookups["03"][0] == {"tool": "get_purchase_order", "input": {"po": "PO-1124"}, "result": "PO-1124: 1 line, 5,000 Hot cup, 12 oz at $0.38", "ok": True}
    assert lookups["09"] == []


def test_the_dot_field_gets_each_eval_bill_with_its_real_outcome():
    f = export_site.field(ROOT / "evals" / "results")
    assert f["file"] == "m5a-subscription-claude-opus-5-5.json"
    cases = f["cases"]
    assert len(cases) == 50
    assert sum(c["status"] == "exception" for c in cases) == 31 and sum(c["status"] == "ready" for c in cases) == 19
    assert sum(c["document"] == "photo" for c in cases) == 8
    assert sum(c["exact"] for c in cases) == 49 and sum(c["safe"] for c in cases) == 50
    assert set(cases[0]) == {"id", "document", "status", "exact", "safe"}


def test_each_recorded_run_carries_the_tokens_of_each_model_call():
    rec = export_site.recorded_runs(ROOT / "replays" / "claude-opus-5-5-low-run2")
    run = next(r for r in rec["runs"] if r["sample"] == "03")
    assert [u["step"] for u in run["usage"]] == ["read", "investigate", "investigate", "investigate"]
    assert run["usage"][0] == {"step": "read", "input": 2, "cache_write": 2641, "cache_read": 1512, "output": 624, "tokens": 4779}
    assert len(run["usage"]) == run["calls"]


def test_the_layouts_come_from_the_studio_presets():
    layouts = export_site.layouts(ROOT / "web" / "src" / "studio" / "presets.ts")
    assert [l["id"] for l in layouts] == ["01", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14"]
    assert layouts[0]["name"] == "Bills up front" and layouts[0]["default"] is True
    assert sum(l["default"] for l in layouts) == 1


def test_readme_blocks_are_filled_between_their_markers_and_nothing_else_changes():
    text = "intro\n<!-- generated:a -->\nold\n<!-- /generated:a -->\nmiddle\n<!-- generated:b -->\n<!-- /generated:b -->\nend\n"
    out = export_site.fill_readme(text, {"a": "new A", "b": "new B"})
    assert out == "intro\n<!-- generated:a -->\nnew A\n<!-- /generated:a -->\nmiddle\n<!-- generated:b -->\nnew B\n<!-- /generated:b -->\nend\n"
    with pytest.raises(ValueError):
        export_site.fill_readme("no markers here", {"a": "x"})


def test_the_results_block_reads_the_numbers_from_the_data():
    data = {
        "evals": export_site.eval_runs(ROOT / "evals" / "results"),
        "recorded": export_site.recorded_runs(ROOT / "replays" / "claude-opus-5-5-low-run2"),
        "tests": {"python": {"passed": 367}, "web": {"passed": 118}},
        "model": {"name": "Claude Opus 5.5"},
    }
    block = export_site.readme_blocks(data, export_site.layouts(ROOT / "web" / "src" / "studio" / "presets.ts"))["results"]
    assert "| Claude Opus 5.5 | standard | 50 | 49 of 50 | 504 of 504 | 21 of 21 | 50 of 50 | $0.0713 | 15.8 |" in block
    assert "| Claude Opus 5.5 | hard | 10 | 10 of 10 | 170 of 170 |" in block
    assert "13 of 13" in block and "40 model calls" in block
    # was: "PRICE_VARIANCE" not in block - vacuous, the block never lists flags; it must say what the scripted rows prove
    assert "| Scripted reader (proves the graders, not a model) | standard | 50 | 49 of 50 |" in block


def test_the_studio_counts_and_the_default_look_come_from_the_presets():
    k = export_site.studio(ROOT / "web" / "src" / "studio" / "presets.ts")
    assert (k["palettes"], k["fonts"]) == (21, 15)
    assert (k["palette"], k["font"]) == ("Golden hour on paper", "Barlow Condensed caps + DM Sans")


VITEST_FILE_FAILED = " Test Files  1 failed | 11 passed (12)\n      Tests  117 passed (117)\n"


def test_a_vitest_file_that_fails_to_load_counts_as_a_failure():
    assert export_site.count_vitest(VITEST_FILE_FAILED)["failed"] >= 1


def test_a_red_exit_code_refuses_even_when_the_counts_look_green(tmp_path):
    out = tmp_path / "site-data.json"
    out.write_text('{"old": true}\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        export_site.export(out, lambda _: {"python": (1, GREEN_PY), "web": (0, GREEN_WEB)})
    assert out.read_text(encoding="utf-8") == '{"old": true}\n'


@pytest.mark.parametrize("failure", [KeyboardInterrupt, FileNotFoundError])
def test_an_interrupted_or_broken_run_puts_the_old_file_back(tmp_path, failure):
    out = tmp_path / "site-data.json"
    out.write_text('{"old": true}\n', encoding="utf-8")

    def broken(_):
        raise failure("npx")

    with pytest.raises(failure):
        export_site.export(out, broken)
    assert out.read_text(encoding="utf-8") == '{"old": true}\n'


def test_a_recorded_run_that_errors_on_replay_is_not_exported_as_no_lookups(monkeypatch):
    import ledger_desk.runner as runner

    monkeypatch.setattr(runner, "run_case", lambda *a, **k: {"id": "03", "outcome": {}, "error": "ReplayMismatch: asked for something else"})
    with pytest.raises(RuntimeError, match="03"):
        export_site.replayed_lookups(ROOT / "replays" / "claude-opus-5-5-low-run2", "ledger_desk_test_export", samples=["03"])


def test_the_readme_intro_names_the_live_site_and_where_it_runs():
    data = {
        "evals": export_site.eval_runs(ROOT / "evals" / "results"),
        "recorded": export_site.recorded_runs(ROOT / "replays" / "claude-opus-5-5-low-run2"),
        "tests": {"python": {"passed": 1}, "web": {"passed": 1}},
        "model": {"name": "Claude Opus 5.5"},
    }
    intro = export_site.readme_blocks(data, export_site.layouts(ROOT / "web" / "src" / "studio" / "presets.ts"))["intro"]
    assert "https://ledger-desk.mniznik.com" in intro
    for service in ("Azure Container Apps", "Azure Database for PostgreSQL", "Azure Key Vault", "Azure Static Web Apps", "Terraform"):
        assert service in intro, service
    assert "Not deployed" not in intro
