"""Run-and-record: each sample invoice through the workflow to the approval pause, compared with its
ground truth, and written down with every model reply so it can be replayed for $0.

A replay feeds the recorded replies back through the same code (rules, checks, workflow); it does
not just show stored output. If the code now asks the model something different from what was
recorded, the replay stops instead of pairing a reply with the wrong question.
"""

import json

import pytest

from ledger_desk.cli import main
from ledger_desk.invoices import load_case
from ledger_desk.runner import ReplayMismatch, ReplayModel, ScriptedReader, run_case


def test_run_records_each_invoice_and_compares_it_with_the_ground_truth(erp_db, tmp_path, capsys):
    rec = tmp_path / "rec"
    assert main(["run", "--db", erp_db, "--ids", "01,09,12", "--model", "scripted", "--record", str(rec), "--docs", str(tmp_path / "docs")]) == 0
    out = capsys.readouterr().out
    assert "3 of 3 match their ground truth" in out

    files = sorted(p.name for p in rec.iterdir())
    assert files == ["01.json", "09.json", "12.json", "summary.json"]
    r = json.loads((rec / "12.json").read_text(encoding="utf-8"))
    assert r["outcome"]["status"] == "exception" and [f["code"] for f in r["outcome"]["flags"]] == ["SUSPICIOUS_TEXT"]
    assert r["match"] == {"status": True, "flags": True, "approver": True, "account": True, "all": True}
    assert [x["task"] for x in r["replies"]] == ["read", "suggest_account", "investigate"]
    assert r["model"] == "scripted" and r["via"] == "scripted" and r["seconds"] >= 0
    assert r["metrics"]["model_calls"] == 3

    summary = json.loads((rec / "summary.json").read_text(encoding="utf-8"))
    assert summary["matched"] == 3 and summary["total"] == 3 and summary["errors"] == 0
    assert set(summary["invoices"]) == {"01", "09", "12"}


def test_a_mismatch_is_reported_per_field_and_fails_the_run(erp_db, tmp_path, capsys):
    # a reader that misreads invoice 01's total: the totals check catches it
    model = ScriptedReader(overrides={"01": {"total": "6020.00"}})
    record = run_case(load_case("01"), model, erp_db, tmp_path)
    assert record["outcome"]["status"] == "exception"
    assert record["match"]["status"] is False and record["match"]["all"] is False


def test_a_replay_reproduces_the_run_without_a_model(erp_db, tmp_path):
    first = run_case(load_case("08"), ScriptedReader(), erp_db, tmp_path)
    replay = ReplayModel(first["replies"])
    again = run_case(load_case("08"), replay, erp_db, tmp_path)
    assert again["outcome"] == first["outcome"]
    assert replay.remaining == 0  # every recorded reply was used, in order


def test_a_replay_stops_when_the_code_asks_something_else(erp_db, tmp_path):
    # invoice 08 asks read, suggest_account, investigate; a recording made before account
    # suggestions existed holds read, investigate: the second question no longer matches
    first = run_case(load_case("08"), ScriptedReader(), erp_db, tmp_path)
    replies = [r for r in first["replies"] if r["task"] != "suggest_account"]
    with pytest.raises(ReplayMismatch, match="recorded for 'investigate', the code asked for 'suggest_account'"):
        run_case(load_case("08"), ReplayModel(replies), erp_db, tmp_path)


def test_a_replay_that_runs_out_stops_too(erp_db, tmp_path):
    first = run_case(load_case("09"), ScriptedReader(), erp_db, tmp_path)
    with pytest.raises(ReplayMismatch, match="after the recording's 1 replies"):
        run_case(load_case("09"), ReplayModel(first["replies"][:1]), erp_db, tmp_path)


def test_a_model_failure_on_one_invoice_is_recorded_and_the_rest_still_run(erp_db, tmp_path, capsys, monkeypatch):
    from ledger_desk import runner
    from ledger_desk.subscription import ModelUnavailable

    class Down:
        def __call__(self, request):
            raise ModelUnavailable("claude exited 1 without a result: Not logged in")

    real = runner.make_model
    monkeypatch.setattr(runner, "make_model", lambda name, **kw: Down() if name == "subscription" else real(name, **kw))
    rec = tmp_path / "rec"
    assert main(["run", "--db", erp_db, "--ids", "01,09", "--model", "subscription", "--record", str(rec), "--docs", str(tmp_path / "docs")]) == 1
    r = json.loads((rec / "01.json").read_text(encoding="utf-8"))
    assert r["error"].startswith("ModelUnavailable") and r["match"]["all"] is False
    summary = json.loads((rec / "summary.json").read_text(encoding="utf-8"))
    assert summary["errors"] == 2 and summary["matched"] == 0
    assert "2 errors" in capsys.readouterr().out
