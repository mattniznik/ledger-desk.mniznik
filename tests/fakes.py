"""Test doubles for the model: a scripted model client, and the reading a perfect reader would
return for each sample invoice (built from its YAML ground truth, with each field's source text
exactly as the PDF prints it)."""

from __future__ import annotations

import json

from ledger_desk.model import ModelReply, ToolCall
from ledger_desk.scripted import perfect_reading, usd  # noqa: F401  (re-exported for the tests)


def read_reply(reading: dict, usage=None) -> ModelReply:
    return ModelReply(stop_reason="end_turn", text=json.dumps(reading), usage=usage or {"input_tokens": 3000, "output_tokens": 600}, model="claude-opus-5-5")


def tool_reply(name: str, args: dict, call_id: str = "t1") -> ModelReply:
    return ModelReply(stop_reason="tool_use", tool_calls=[ToolCall(call_id, name, args)], usage={"input_tokens": 1000, "output_tokens": 100}, model="claude-opus-5-5")


def text_reply(text: str) -> ModelReply:
    return ModelReply(stop_reason="end_turn", text=text, usage={"input_tokens": 1500, "output_tokens": 200}, model="claude-opus-5-5")


class ScriptedModel:
    """Plays back replies in order (the last one repeats) and records every request."""

    def __init__(self, *replies: ModelReply):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, request: dict) -> ModelReply:
        self.requests.append(json.loads(json.dumps(request, default=str)))
        return self.replies[min(len(self.requests) - 1, len(self.replies) - 1)]
