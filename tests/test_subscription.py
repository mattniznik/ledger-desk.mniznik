"""The subscription adapter: `claude -p` from Claude Code, driven through a fake runner (no call).

Development and the recorded runs call the model through a Claude Code subscription login. These
tests pin what that path must never do (carry an API key, load the user's hooks, CLAUDE.md or MCP
servers, give Claude tools of its own) and how its replies map onto the port.
"""

import json
from pathlib import Path

import pytest

from ledger_desk.agent import agent_tools, investigate
from ledger_desk.invoices import load_case
from ledger_desk.model import cost_usd
from ledger_desk.reading import READ_SYSTEM, Extraction, read_invoice
from ledger_desk.subscription import ClaudeCodeModel, ModelUnavailable, child_env

from fakes import perfect_reading

OUT = Path(__file__).resolve().parents[1] / "out"


def result_event(structured=None, *, stop_reason="tool_use", subtype="success", is_error=False, result="", usage=None, model="claude-opus-5-5"):
    usage = usage or {"input_tokens": 2, "output_tokens": 82, "cache_creation_input_tokens": 3117, "cache_read_input_tokens": 0, "cache_creation": {"ephemeral_1h_input_tokens": 3117, "ephemeral_5m_input_tokens": 0}}
    ev = {"type": "result", "subtype": subtype, "is_error": is_error, "stop_reason": stop_reason, "result": result, "usage": usage, "modelUsage": {model: {"inputTokens": usage["input_tokens"]}}, "total_cost_usd": 0.0267}
    if structured is not None:
        ev["structured_output"] = structured
    return ev


class FakeRunner:
    """Stands in for the claude process: records each call, replies with scripted stream-json."""

    def __init__(self, *events, returncode=0, stderr=""):
        self.events = list(events)
        self.calls = []
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, cmd, stdin, env, cwd):
        self.calls.append({"cmd": cmd, "stdin": stdin, "env": env, "cwd": cwd})
        ev = self.events[min(len(self.calls) - 1, len(self.events) - 1)]
        lines = [json.dumps({"type": "system", "subtype": "init"})] + ([json.dumps(ev)] if ev else [])
        return self.returncode, "\n".join(lines) + "\n", self.stderr

    def flag(self, name, call=-1):
        cmd = self.calls[call]["cmd"]
        return cmd[cmd.index(name) + 1]

    def message(self, call=-1):
        return json.loads(self.calls[call]["stdin"].strip())["message"]


def test_child_env_drops_api_keys_and_turns_off_mats_context():
    env = child_env({"ANTHROPIC_API_KEY": "placeholder", "ANTHROPIC_AUTH_TOKEN": "placeholder", "PATH": "p", "USERPROFILE": "u"})
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["PATH"] == "p" and env["USERPROFILE"] == "u"  # the login lives under the profile; keep it
    for var in ("CLAUDE_CODE_DISABLE_CLAUDE_MDS", "CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS", "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS"):
        assert env[var] == "1"


def test_the_command_is_restricted_and_keeps_the_subscription_login():
    runner = FakeRunner(result_event(perfect_reading(load_case("01"))))
    ClaudeCodeModel(runner=runner, model="claude-opus-5-5", effort="low")({"task": "read", "system": READ_SYSTEM, "document": {"media_type": "application/pdf", "data": "AAAA"}, "schema": Extraction.model_json_schema()})
    cmd = runner.calls[0]["cmd"]
    for f in ("-p", "--restricted", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert f in cmd
    assert runner.flag("--tools") == ""  # Claude gets no tools of its own: no files, no shell, no web
    assert runner.flag("--input-format") == "stream-json"
    assert runner.flag("--model") == "claude-opus-5-5" and runner.flag("--effort") == "low"
    assert "--bare" not in cmd  # bare mode never reads the subscription login (headless docs)
    assert "bypassPermissions" not in cmd
    assert "ANTHROPIC_API_KEY" not in runner.calls[0]["env"]
    assert runner.calls[0]["cwd"] != str(Path.cwd())  # an empty folder: no project .claude or .mcp.json


def test_reading_sends_the_pdf_as_a_document_block_with_the_schema():
    case = load_case("01")
    runner = FakeRunner(result_event(perfect_reading(case)))
    result = read_invoice(OUT / "01-green-coffee-clean.pdf", ClaudeCodeModel(runner=runner))
    assert result.status == "read" and result.invoice.number == "GCI-2301"
    block = runner.message()["content"][0]
    assert block["type"] == "document" and block["source"]["type"] == "base64" and block["source"]["media_type"] == "application/pdf"
    assert runner.flag("--system-prompt") == READ_SYSTEM
    assert json.loads(runner.flag("--json-schema")) == Extraction.model_json_schema()


def test_reading_sends_a_photo_as_an_image_block():
    case = load_case("02")
    runner = FakeRunner(result_event(perfect_reading(case)))
    read_invoice(OUT / "02-green-coffee-photo-partial.jpg", ClaudeCodeModel(runner=runner))
    block = runner.message()["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/jpeg"


def test_reply_maps_usage_and_model_and_prices_one_hour_cache_writes():
    runner = FakeRunner(result_event({"x": 1}))
    reply = ClaudeCodeModel(runner=runner)({"task": "read", "system": "s", "document": {"media_type": "application/pdf", "data": "AAAA"}, "schema": {"type": "object"}})
    assert reply.stop_reason == "end_turn" and json.loads(reply.text) == {"x": 1}
    assert reply.model == "claude-opus-5-5"
    assert reply.usage["input_tokens"] == 2 and reply.usage["output_tokens"] == 82 and reply.usage["cache_creation_input_tokens"] == 3117
    assert reply.usage["via"] == "subscription"
    # 1-hour writes are 2x input ($8/M on Opus 5.5), not the 5-minute 1.25x (prompt-caching docs)
    assert cost_usd("claude-opus-5-5", reply.usage) == pytest.approx((2 * 4 + 3117 * 8 + 82 * 20) / 1_000_000)


def test_the_model_is_the_one_that_answered_not_claude_codes_side_call():
    # Measured 2026-11-14 (n=1): a real read listed claude-haiku-5-5 first in modelUsage (Claude
    # Code's own side call, 1,171 in / 15 out) and claude-opus-5-5, which did the reading, second.
    ev = result_event({"x": 1})
    ev["modelUsage"] = {
        "claude-haiku-5-5": {"inputTokens": 1171, "outputTokens": 15, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0},
        "claude-opus-5-5": {"inputTokens": 2, "outputTokens": 82, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 3117},
    }
    reply = ClaudeCodeModel(runner=FakeRunner(ev), model="claude-opus-5-5")({"task": "read", "system": "s", "document": {"media_type": "application/pdf", "data": "AAAA"}, "schema": {"type": "object"}})
    assert reply.model == "claude-opus-5-5"
    assert reply.usage["side_calls"] == [{"model": "claude-haiku-5-5", "input_tokens": 1171, "output_tokens": 15}]
    # the side call is Claude Code's, not the app's: the API adapter will not make it, so it is not priced
    assert cost_usd(reply.model, reply.usage) == pytest.approx((2 * 4 + 3117 * 8 + 82 * 20) / 1_000_000)


def test_a_decline_without_structured_output_is_a_refusal_and_goes_to_manual_entry():
    runner = FakeRunner(result_event(None, stop_reason="refusal", result="I can't help with that."))
    result = read_invoice(OUT / "01-green-coffee-clean.pdf", ClaudeCodeModel(runner=runner))
    assert result.status == "manual_entry" and "declined" in result.reason


def test_no_structured_output_without_a_refusal_is_invalid_and_goes_to_manual_entry():
    runner = FakeRunner(result_event(None, stop_reason="end_turn", result="Here is the invoice: ..."))
    result = read_invoice(OUT / "01-green-coffee-clean.pdf", ClaudeCodeModel(runner=runner))
    assert result.status == "manual_entry" and "not valid" in result.reason


@pytest.mark.parametrize(
    "runner",
    [
        FakeRunner(result_event(None, subtype="error_during_execution", is_error=True, result="rate limited")),
        FakeRunner(None, returncode=1, stderr="Not logged in"),
    ],
    ids=["is_error", "no_result"],
)
def test_a_failed_run_raises_instead_of_pretending_to_be_a_reading(runner):
    with pytest.raises(ModelUnavailable):
        ClaudeCodeModel(runner=runner)({"task": "read", "system": "s", "document": {"media_type": "application/pdf", "data": "AAAA"}, "schema": {"type": "object"}})


class StubErp:
    def vendor(self, tax_id=None, name=None):
        return [{"id": "V05", "name": "Espresso Repair Service", "bank_last4": "4417"}]

    def purchase_order(self, po):
        return {}

    def receipts(self, po):
        return []

    def bills(self, **params):
        return []


def test_agent_turns_carry_the_tools_and_map_lookups_and_the_answer():
    case = load_case("08")
    runner = FakeRunner(
        result_event({"tool_calls": [{"name": "get_vendor", "input": {"tax_id": case.invoice.vendor_tax_id}}], "answer": ""}),
        result_event({"tool_calls": [], "answer": "The bank account changed from 4417 to 9921; call the vendor on the number on file."}),
    )
    drafts: list = []
    result = investigate(case.invoice, [{"code": "BANK_CHANGED", "detail": "x"}], ClaudeCodeModel(runner=runner), agent_tools(StubErp(), drafts), drafts)
    assert result.status == "explained" and "9921" in result.explanation and result.tool_calls == 1

    schema = json.loads(runner.flag("--json-schema", call=0))
    names = schema["properties"]["tool_calls"]["items"]["properties"]["name"]["enum"]
    assert set(names) == {"get_vendor", "get_purchase_order", "get_receipts", "get_bills", "draft_vendor_email"}
    assert "get_vendor" in runner.flag("--system-prompt", call=0)  # the catalogue is in the prompt

    second = runner.message(call=1)["content"][0]["text"]
    assert "4417" in second  # the lookup's result went back to the model
    assert "data, not instructions" in second


def test_a_plain_structured_request_sends_the_prompt_and_the_schema():
    # account suggestion: no document, no tools, a prompt and a schema
    schema = {"type": "object", "properties": {"account": {"type": "string", "enum": ["6200"]}}, "required": ["account"]}
    runner = FakeRunner(result_event({"account": "6200", "reason": "r"}))
    reply = ClaudeCodeModel(runner=runner)({"task": "suggest_account", "system": "sys", "prompt": "Suggest the account.\n{}", "schema": schema})
    assert runner.message()["content"] == [{"type": "text", "text": "Suggest the account.\n{}"}]
    assert json.loads(runner.flag("--json-schema")) == schema and runner.flag("--system-prompt") == "sys"
    assert reply.stop_reason == "end_turn" and json.loads(reply.text)["account"] == "6200"


def test_tool_call_ids_are_stable_for_the_same_conversation():
    req = {"task": "investigate", "system": "s", "tools": [{"name": "get_vendor", "description": "d", "input_schema": {"type": "object"}}], "messages": [{"role": "user", "content": "x"}]}
    ev = result_event({"tool_calls": [{"name": "get_vendor", "input": {}}], "answer": ""})
    a = ClaudeCodeModel(runner=FakeRunner(ev))(req)
    b = ClaudeCodeModel(runner=FakeRunner(ev))(req)
    assert a.stop_reason == "tool_use" and a.tool_calls[0].id == b.tool_calls[0].id
