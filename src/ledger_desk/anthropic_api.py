"""The model through the Anthropic API with ledger-desk's own key: the deployed demo's client.

Locally every model call goes through a Claude Code subscription login (subscription.py); this
adapter is for the deployed demo, which needs an API key of its own. It is built and tested
against a fake SDK; it has never made a call.

The key is read from `.env.local` as LEDGER_DESK_ANTHROPIC_KEY and passed to the client
explicitly. It is never read from ANTHROPIC_API_KEY or any environment variable, and never printed.

Request shapes follow the claude-api skill (read 2026-11-14):
- a PDF as a base64 `document` block, a photo as an `image` block;
- structured outputs through `output_config.format` (json_schema), with every object closed by
  `additionalProperties: false`; effort in the same `output_config`;
- the agent's tools as native tools with `strict: true` and closed schemas, and no `tool_choice`,
  because forcing a tool returns a 400 on Opus 5.5;
- the system prompt as a cached block (`cache_control: ephemeral`, the 5-minute default).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Callable

from .model import ModelReply, ToolCall

ROOT = Path(__file__).resolve().parents[2]
KEY_NAME = "LEDGER_DESK_ANTHROPIC_KEY"
MAX_TOKENS = 16000


class KeyMissing(RuntimeError):
    pass


def read_key(path: Path = ROOT / ".env.local") -> str:
    """The key from the file, by name. The error never repeats what is in the file."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise KeyMissing(f"no {path.name}: put {KEY_NAME}=... in it (it is gitignored)")
    for line in lines:
        name, sep, value = line.partition("=")
        if sep and name.strip() == KEY_NAME and value.strip():
            return value.strip().strip('"').strip("'")
    raise KeyMissing(f"{path.name} has no {KEY_NAME} line")


def closed(schema: dict) -> dict:
    """The schema with every object closed (additionalProperties: false), as strict tools and
    structured outputs require; the input is not changed."""
    out = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(out)
    return out


def _default_client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


class AnthropicModel:
    via = "api"

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "low", client=None, key_file: Path | None = None, client_factory: Callable[[str], object] | None = None):
        self.model = model
        self.effort = effort
        self.client = client or (client_factory or _default_client)(read_key(key_file or ROOT / ".env.local"))

    def _system(self, text: str) -> list[dict]:
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    def __call__(self, request: dict) -> ModelReply:
        kwargs = {"model": self.model, "max_tokens": MAX_TOKENS, "system": self._system(request["system"])}
        if "tools" in request:
            kwargs["messages"] = request["messages"]
            kwargs["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": closed(t["input_schema"]), "strict": True} for t in request["tools"]]
            kwargs["output_config"] = {"effort": self.effort}
        else:
            if "document" in request:
                doc = request["document"]
                kind = "document" if doc["media_type"] == "application/pdf" else "image"
                content = [{"type": kind, "source": {"type": "base64", "media_type": doc["media_type"], "data": doc["data"]}}, {"type": "text", "text": "Read this invoice."}]
            else:
                content = [{"type": "text", "text": request["prompt"]}]
            kwargs["messages"] = [{"role": "user", "content": content}]
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": closed(request["schema"])}, "effort": self.effort}
        return self._reply(self.client.messages.create(**kwargs))

    def _reply(self, r) -> ModelReply:
        texts = [b.text for b in r.content if getattr(b, "type", "") == "text"]
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in r.content if getattr(b, "type", "") == "tool_use"]
        u = r.usage
        usage = {k: getattr(u, k, 0) or 0 for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
        cc = getattr(u, "cache_creation", None)
        if cc is not None:
            usage["cache_creation"] = {k: getattr(cc, k, 0) or 0 for k in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")}
        usage["via"] = self.via
        return ModelReply(r.stop_reason, "".join(texts), calls, usage, r.model)
