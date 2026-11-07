"""Thin Anthropic Messages API client (HTTP via `requests`, no SDK dependency).

`LLMClient` is a protocol so tests can inject a scripted client. Production code only
ever uses `AnthropicClient`; there is no silent fallback that fabricates answers.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

import requests

from app.core.config import Settings, get_settings

log = logging.getLogger("quoteiq.llm")


class LLMUnavailable(RuntimeError):
    """No API key configured — callers must show a clear 'AI unavailable' state."""


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    model: str

    def create(self, *, system: str, messages: list[dict], tools: list[dict] | None = None,
               tool_choice: dict | None = None, max_tokens: int = 4096) -> dict: ...


class AnthropicClient:
    def __init__(self, settings: Settings | None = None):
        s = settings or get_settings()
        if not s.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set — AI extraction and analysis are disabled.")
        self._key = s.anthropic_api_key
        self.model = s.anthropic_model
        self._url = s.anthropic_api_url.rstrip("/") + "/v1/messages"

    def create(self, *, system: str, messages: list[dict], tools: list[dict] | None = None,
               tool_choice: dict | None = None, max_tokens: int = 4096) -> dict:
        body: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens, "system": system, "messages": messages}
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        last = None
        for attempt in range(4):
            try:
                r = requests.post(self._url, headers=headers, data=json.dumps(body), timeout=240)
            except requests.RequestException as e:
                last = f"network error: {e.__class__.__name__}"
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 529):
                last = f"HTTP {r.status_code}"
                time.sleep(min(30, 2 ** (attempt + 1)))
                continue
            # 4xx other than rate limit: not retryable. Never log the request (may contain documents).
            try:
                msg = r.json().get("error", {}).get("message", "")
            except ValueError:
                msg = r.text[:200]
            raise LLMError(f"Anthropic API HTTP {r.status_code}: {msg}")
        raise LLMError(f"Anthropic API failed after retries ({last})")


def get_llm(settings: Settings | None = None) -> Optional[AnthropicClient]:
    s = settings or get_settings()
    return AnthropicClient(s) if s.ai_enabled else None


# ------------------------------------------------------------------ helpers
def image_block(path: str | Path, max_side: int = 1800) -> dict:
    """Encode an image for the vision model (downscaled to keep payload reasonable)."""
    import cv2

    img = cv2.imread(str(path))
    h, w = img.shape[:2]
    f = min(1.0, max_side / max(h, w))
    if f < 1.0:
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.b64encode(buf.tobytes()).decode()}}


def tool_uses(resp: dict) -> list[dict]:
    return [b for b in resp.get("content", []) if b.get("type") == "tool_use"]


def text_of(resp: dict) -> str:
    return "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text").strip()


def inline_schema(schema: dict) -> dict:
    """Resolve $defs/$ref so the tool input_schema is self-contained."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                merged = {**walk(defs[name]), **{k: v for k, v in node.items() if k != "$ref"}}
                return merged
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


class ScriptedLLM:
    """TEST-ONLY client that replays a scripted sequence of responses.

    Each entry is either a response dict or a callable(system, messages, tools) -> dict.
    Used to exercise the tool loop, validation and retry paths without network access.
    """

    def __init__(self, script: list[dict | Callable[..., dict]], model: str = "scripted-test-model"):
        self.script = list(script)
        self.calls: list[dict] = []
        self.model = model

    def create(self, *, system, messages, tools=None, tool_choice=None, max_tokens=4096):
        self.calls.append({"system": system, "messages": json.loads(json.dumps(messages, default=str)),
                           "tools": tools, "tool_choice": tool_choice})
        if not self.script:
            raise LLMError("ScriptedLLM exhausted")
        step = self.script.pop(0)
        return step(system, messages, tools) if callable(step) else step
