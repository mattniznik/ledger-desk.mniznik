"""The API-key adapter: the deployed demo's model client, on the Anthropic SDK.

Built and tested against a fake SDK: no key is used. Request shapes follow the claude-api skill
(read 2026-11-14): a PDF as a base64 document block, a photo as an image block, structured outputs through
`output_config.format`, effort in the same `output_config`, strict tools with
`additionalProperties: false`, no forced `tool_choice` (a 400 on Opus 5.5), the system prompt
cached. The key is read from `.env.local` as LEDGER_DESK_ANTHROPIC_KEY and passed explicitly; never
from ANTHROPIC_API_KEY, never printed.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ledger_desk.agent import agent_tools, investigate
from ledger_desk.anthropic_api import AnthropicModel, KeyMissing, read_key
from ledger_desk.invoices import load_case
from ledger_desk.reading import READ_SYSTEM, read_invoice

from fakes import perfect_reading

OUT = Path(__file__).resolve().parents[1] / "out"


def response(blocks, stop_reason="end_turn", model="claude-opus-5-5"):
    usage = SimpleNamespace(input_tokens=1200, output_tokens=300, cache_creation_input_tokens=900, cache_read_input_tokens=0, cache_creation=SimpleNamespace(ephemeral_5m_input_tokens=900, ephemeral_1h_input_tokens=0))
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=usage, model=model)


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(i, name, args):
    return SimpleNamespace(type="tool_use", id=i, name=name, input=args)


class FakeSDK:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


def test_the_key_comes_from_env_local_only_and_is_passed_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-env-value-that-must-be-ignored")
    f = tmp_path / ".env.local"
    f.write_text("# local secrets\nOTHER=1\nLEDGER_DESK_ANTHROPIC_KEY=dummy-for-the-test\n", encoding="utf-8")
    assert read_key(f) == "dummy-for-the-test"
    seen = {}
    AnthropicModel(key_file=f, client_factory=lambda api_key: seen.setdefault("api_key", api_key) and FakeSDK())
    assert seen["api_key"] == "dummy-for-the-test"


def test_the_api_model_is_selectable_and_without_a_key_it_stops_with_a_clear_error(tmp_path, monkeypatch):
    from ledger_desk import anthropic_api, runner

    monkeypatch.setattr(anthropic_api, "ROOT", tmp_path)  # a folder with no .env.local
    with pytest.raises(KeyMissing, match="LEDGER_DESK_ANTHROPIC_KEY"):
        runner.make_model("api")


def test_no_key_file_or_no_key_line_is_a_clear_error_that_does_not_echo_the_file(tmp_path):
    with pytest.raises(KeyMissing, match="LEDGER_DESK_ANTHROPIC_KEY"):
        read_key(tmp_path / "missing.env")
    f = tmp_path / ".env.local"
    f.write_text("SOMETHING_SECRET=abc123\n", encoding="utf-8")
    with pytest.raises(KeyMissing) as e:
        read_key(f)
    assert "abc123" not in str(e.value)


def test_reading_sends_the_pdf_with_the_schema_effort_and_a_cached_system_prompt():
    sdk = FakeSDK(response([text(json.dumps(perfect_reading(load_case("01"))))]))
    result = read_invoice(OUT / "01-green-coffee-clean.pdf", AnthropicModel(client=sdk, model="claude-opus-5-5", effort="low"))
    assert result.status == "read" and result.invoice.number == "GCI-2301"
    call = sdk.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["max_tokens"] > 0
    block = call["messages"][0]["content"][0]
    assert block["type"] == "document" and block["source"]["type"] == "base64" and block["source"]["media_type"] == "application/pdf"
    assert call["system"] == [{"type": "text", "text": READ_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema" and call["output_config"]["effort"] == "low"
    assert fmt["schema"]["additionalProperties"] is False  # every object closed, as structured outputs need
    assert fmt["schema"]["$defs"]["ExtractedLine"]["additionalProperties"] is False
    assert "tool_choice" not in call


def test_a_photo_goes_as_an_image_block():
    sdk = FakeSDK(response([text(json.dumps(perfect_reading(load_case("02"))))]))
    read_invoice(OUT / "02-green-coffee-photo-partial.jpg", AnthropicModel(client=sdk))
    assert sdk.calls[0]["messages"][0]["content"][0]["type"] == "image"


def test_a_refusal_maps_to_manual_entry_and_usage_is_kept():
    sdk = FakeSDK(response([text("I can't help with that.")], stop_reason="refusal"))
    result = read_invoice(OUT / "01-green-coffee-clean.pdf", AnthropicModel(client=sdk))
    assert result.status == "manual_entry" and "declined" in result.reason
    assert result.usage[0]["input_tokens"] == 1200 and result.usage[0]["cache_creation_input_tokens"] == 900
    assert result.usage[0]["via"] == "api" and result.usage[0]["model"] == "claude-opus-5-5"


class StubErp:
    def vendor(self, tax_id=None, name=None):
        return [{"id": "V05", "bank_last4": "4417"}]

    def purchase_order(self, po):
        return {}

    def receipts(self, po):
        return []

    def bills(self, **params):
        return []


def test_agent_turns_use_native_strict_tools_with_no_forced_choice():
    case = load_case("08")
    sdk = FakeSDK(
        response([tool_use("toolu_1", "get_vendor", {"tax_id": case.invoice.vendor_tax_id})], stop_reason="tool_use"),
        response([text("The account changed from 4417 to 9921; call the vendor on the number on file.")]),
    )
    drafts: list = []
    result = investigate(case.invoice, [{"code": "BANK_CHANGED", "detail": "x"}], AnthropicModel(client=sdk), agent_tools(StubErp(), drafts), drafts)
    assert result.status == "explained" and result.tool_calls == 1 and "9921" in result.explanation
    first = sdk.calls[0]
    assert "tool_choice" not in first
    assert {t["name"] for t in first["tools"]} == {"get_vendor", "get_purchase_order", "get_receipts", "get_bills", "draft_vendor_email"}
    assert all(t["strict"] is True and t["input_schema"]["additionalProperties"] is False for t in first["tools"])
    second = sdk.calls[1]["messages"]
    assert second[-1]["content"][0]["type"] == "tool_result" and second[-1]["content"][0]["tool_use_id"] == "toolu_1"
