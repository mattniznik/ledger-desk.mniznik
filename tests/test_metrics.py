"""Run metrics count every input token, cached or not.

Measured in the first real run (2026-11-14): the run line printed "80 in" for 39 model calls,
because only uncached input was summed, while almost every prompt was a cache write or a cache
read. The dollar figure counted them; the token figure did not.
"""

import json

from ledger_desk.cli import main
from ledger_desk.model import ModelReply, summarize


def test_summarize_adds_cache_writes_and_reads():
    calls = [
        {"model": "claude-opus-5-5", "input_tokens": 2, "output_tokens": 600, "cache_creation_input_tokens": 3117, "cache_read_input_tokens": 0},
        {"model": "claude-opus-5-5", "input_tokens": 3, "output_tokens": 80, "cache_creation_input_tokens": 628, "cache_read_input_tokens": 3287},
    ]
    m = summarize(calls)
    assert (m["input_tokens"], m["cache_write_tokens"], m["cache_read_tokens"], m["output_tokens"]) == (5, 3745, 3287, 680)
    assert m["model_calls"] == 2


def test_summarize_of_calls_without_cache_fields_counts_zero():
    m = summarize([{"model": "scripted", "input_tokens": 0, "output_tokens": 0}])
    assert (m["cache_write_tokens"], m["cache_read_tokens"]) == (0, 0)


def test_the_run_line_shows_cached_input(erp_db, tmp_path, capsys, monkeypatch):
    from ledger_desk import runner

    class Cached(runner.ScriptedReader):
        def __call__(self, request):
            reply = super().__call__(request)
            return ModelReply(reply.stop_reason, reply.text, reply.tool_calls, {"input_tokens": 2, "output_tokens": 10, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 500}, "claude-opus-5-5")

    monkeypatch.setattr(runner, "make_model", lambda name, **kw: Cached())
    main(["run", "--db", erp_db, "--ids", "09", "--docs", str(tmp_path), "--record", str(tmp_path / "rec")])
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert "cache write 2,000" in line and "cache read 1,000" in line  # 2 calls on invoice 09: read, suggest_account
    summary = json.loads((tmp_path / "rec" / "summary.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["cache_write_tokens"] == 2000
