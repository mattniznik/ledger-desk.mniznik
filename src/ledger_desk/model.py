"""The model port: what the app asks a model and what it gets back.

Reading and the agent talk to a `ModelClient`, never to an SDK directly, so they are tested with
a scripted fake and the Anthropic adapter is one small file (anthropic_api.py). The reply carries the stop reason, because a refusal has to be handled
(it sends the invoice to a person), and the usage, because every run reports its cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ModelReply:
    stop_reason: str  # "end_turn", "tool_use", "max_tokens", "refusal", ...
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    model: str = ""


class ModelClient(Protocol):
    def __call__(self, request: dict) -> ModelReply: ...


# USD per million tokens (Anthropic pricing page, read 2026-11-12): input, 5-minute cache write,
# cache read, output. A model not listed gets no price rather than a guess.
PRICES = {
    "claude-opus-5-5": (4.0, 5.0, 0.20, 20.0),
    "claude-sonnet-5-5": (2.0, 2.5, 0.10, 10.0),
    "claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50),
}


def cost_usd(model: str, usage: dict) -> float | None:
    p = PRICES.get(model)
    if p is None:
        return None
    input_, write, read, output = p
    # `cache_creation` splits the writes by TTL; 1-hour writes cost 2x input, 5-minute 1.25x
    # (claude-api skill, prompt-caching.md, read 2026-11-14). Claude Code writes 1-hour entries.
    one_hour = (usage.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0
    five_minute = (usage.get("cache_creation_input_tokens") or 0) - one_hour
    return (
        usage.get("input_tokens", 0) * input_
        + five_minute * write
        + one_hour * 2 * input_
        + (usage.get("cache_read_input_tokens") or 0) * read
        + usage.get("output_tokens", 0) * output
    ) / 1_000_000


def summarize(calls: list[dict]) -> dict:
    """Run metrics from every model call's usage: calls, tokens, dollars (None if any is unpriced)."""
    costs = [cost_usd(c.get("model", ""), c) for c in calls]
    return {
        "model_calls": len(calls),
        "input_tokens": sum(c.get("input_tokens", 0) for c in calls),  # uncached input only
        "cache_write_tokens": sum(c.get("cache_creation_input_tokens") or 0 for c in calls),
        "cache_read_tokens": sum(c.get("cache_read_input_tokens") or 0 for c in calls),
        "output_tokens": sum(c.get("output_tokens", 0) for c in calls),
        "cost_usd": None if any(c is None for c in costs) else sum(costs),
    }


def usage_record(reply: ModelReply, step: str) -> dict:
    return {"step": step, "model": reply.model, **reply.usage}
