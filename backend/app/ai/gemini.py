"""Google Gemini adapter (free tier via Google AI Studio).

Implements the same `create()` contract as AnthropicClient: it accepts Anthropic-style
messages/tools and returns an Anthropic-style response ({"content": [text|tool_use blocks],
"stop_reason": ...}). Everything above this layer (extraction, co-pilot, analyst) is unchanged.

Translation notes
- system            -> systemInstruction
- user/assistant    -> user/model
- image block       -> inlineData
- tool_use          -> functionCall (original Gemini part kept so thoughtSignature round-trips)
- tool_result       -> functionResponse (name recovered from the matching tool_use id)
- tools             -> functionDeclarations with a sanitised OpenAPI-subset schema
- tool_choice tool  -> functionCallingConfig mode ANY + allowedFunctionNames
Free-tier limits are tight (a few requests/minute), so 429s are retried with the server's delay.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

import requests

from app.ai.llm import LLMError, LLMUnavailable
from app.core.config import Settings, get_settings

log = logging.getLogger("quoteiq.gemini")

_KEEP = {"type", "description", "enum", "items", "properties", "required", "nullable", "format",
         "minimum", "maximum", "minItems", "maxItems"}
_FORMATS = {"date-time", "enum"}


def sanitize_schema(node: Any) -> Any:
    """JSON Schema (Pydantic, $refs already inlined) -> Gemini's OpenAPI-3 subset.

    - anyOf [X, null] -> X with nullable: true
    - other anyOf     -> first non-null branch (Gemini rejects most unions)
    - objects without properties (free-form dicts) -> string carrying JSON; parsed back by
      `coerce_json_strings` before Pydantic validation
    """
    if isinstance(node, list):
        return [sanitize_schema(x) for x in node]
    if not isinstance(node, dict):
        return node
    if "anyOf" in node or "oneOf" in node:
        branches = node.get("anyOf") or node.get("oneOf")
        non_null = [b for b in branches if b.get("type") != "null"]
        base = dict(non_null[0]) if non_null else {"type": "string"}
        for k in ("description",):
            if k in node and k not in base:
                base[k] = node[k]
        out = sanitize_schema(base)
        if len(non_null) < len(branches):
            out["nullable"] = True
        return out
    if "const" in node:
        node = {**node, "enum": [node["const"]], "type": node.get("type", "string")}
    t = node.get("type")
    if t == "object" and not node.get("properties"):
        return {"type": "string", "description": (node.get("description", "") + " (JSON object encoded as a string)").strip()}
    out = {}
    for k, v in node.items():
        if k not in _KEEP:
            continue
        if k == "properties":
            out[k] = {pk: sanitize_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = sanitize_schema(v)
        elif k == "format":
            if v in _FORMATS:
                out[k] = v
        elif k == "enum":
            out[k] = [str(x) for x in v]
        else:
            out[k] = v
    if out.get("type") == "integer" and "enum" in out:
        out["type"] = "string"
    if "type" not in out and "enum" in out:
        out["type"] = "string"
    if out.get("type") == "array" and "items" not in out:
        out["items"] = {"type": "string"}
    return out


def coerce_json_strings(value: Any, schema: dict) -> Any:
    """Undo the free-form-object workaround: parse JSON strings where the original schema wanted an object."""
    if not isinstance(schema, dict):
        return value
    if "anyOf" in schema:
        for b in schema["anyOf"]:
            if b.get("type") != "null":
                return coerce_json_strings(value, b)
        return value
    t = schema.get("type")
    if t == "object" and not schema.get("properties"):
        if isinstance(value, str):
            try:
                return json.loads(value) if value.strip() else {}
            except ValueError:
                return {}
        return value
    if t == "object" and isinstance(value, dict):
        props = schema.get("properties", {})
        return {k: coerce_json_strings(v, props.get(k, {})) for k, v in value.items()}
    if t == "array" and isinstance(value, list):
        return [coerce_json_strings(v, schema.get("items", {})) for v in value]
    return value


class GeminiClient:
    def __init__(self, settings: Settings | None = None):
        s = settings or get_settings()
        if not s.gemini_api_key:
            raise LLMUnavailable("GEMINI_API_KEY is not set — AI extraction and analysis are disabled.")
        self._key = s.gemini_api_key
        self.model = s.gemini_model
        self._url = f"{s.gemini_api_url.rstrip('/')}/v1beta/models/{self.model}:generateContent"

    # ------------------------------------------------------------------ request translation
    @staticmethod
    def to_contents(messages: list[dict]) -> list[dict]:
        names: dict[str, str] = {}
        contents = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            blocks = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
            parts = []
            for b in blocks:
                bt = b.get("type")
                if bt == "text":
                    if b.get("text"):
                        parts.append({"text": b["text"]})
                elif bt == "image":
                    src = b["source"]
                    parts.append({"inlineData": {"mimeType": src["media_type"], "data": src["data"]}})
                elif bt == "tool_use":
                    names[b["id"]] = b["name"]
                    parts.append(b.get("_gemini_part") or {"functionCall": {"name": b["name"], "args": b.get("input") or {}}})
                elif bt == "tool_result":
                    content = b.get("content")
                    if isinstance(content, list):
                        content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
                    try:
                        payload = json.loads(content) if isinstance(content, str) else content
                    except ValueError:
                        payload = content
                    if not isinstance(payload, dict):
                        payload = {"result": payload}
                    if b.get("is_error"):
                        payload = {"error": payload.get("result", payload)}
                    parts.append({"functionResponse": {"name": names.get(b["tool_use_id"], "tool"), "response": payload}})
            if not parts:
                parts = [{"text": "(empty)"}]
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].extend(parts)       # Gemini wants alternating turns
            else:
                contents.append({"role": role, "parts": parts})
        return contents

    # ------------------------------------------------------------------ response translation
    @staticmethod
    def from_response(data: dict) -> dict:
        cands = data.get("candidates") or []
        if not cands:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise LLMError(f"Gemini returned no answer ({reason})")
        c = cands[0]
        content = []
        for part in (c.get("content") or {}).get("parts", []):
            if "functionCall" in part:
                fc = part["functionCall"]
                content.append({"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:16]}", "name": fc["name"],
                                "input": fc.get("args") or {}, "_gemini_part": part})
            elif part.get("text") and not part.get("thought"):
                content.append({"type": "text", "text": part["text"]})
        finish = c.get("finishReason", "STOP")
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else (
            "max_tokens" if finish == "MAX_TOKENS" else "end_turn")
        if finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT") and not content:
            raise LLMError(f"Gemini stopped the response ({finish})")
        return {"content": content, "stop_reason": stop, "model": data.get("modelVersion")}

    # ------------------------------------------------------------------ call
    def create(self, *, system: str, messages: list[dict], tools: list[dict] | None = None,
               tool_choice: dict | None = None, max_tokens: int = 4096) -> dict:
        self._schemas = {t["name"]: t["input_schema"] for t in (tools or [])}
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": self.to_contents(messages),
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1},
        }
        if tools:
            body["tools"] = [{"functionDeclarations": [
                {"name": t["name"], "description": t.get("description", "")[:1000],
                 "parameters": sanitize_schema(t["input_schema"])} for t in tools]}]
            if tool_choice and tool_choice.get("type") == "tool":
                body["toolConfig"] = {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [tool_choice["name"]]}}
            else:
                body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        last = None
        for attempt in range(6):
            try:
                r = requests.post(self._url, params={"key": self._key}, json=body, timeout=240)
            except requests.RequestException as e:
                last = f"network error: {e.__class__.__name__}"
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                out = self.from_response(r.json())
                for b in out["content"]:
                    if b["type"] == "tool_use" and b["name"] in self._schemas:
                        b["input"] = coerce_json_strings(b["input"], self._schemas[b["name"]])
                return out
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                wait = min(60, 2 ** (attempt + 2))
                m = re.search(r'"retryDelay":\s*"(\d+)', r.text)
                if m:
                    wait = min(65, int(m.group(1)) + 1)
                log.warning("Gemini %s — retrying in %ss (free-tier rate limits are low)", r.status_code, wait)
                time.sleep(wait)
                continue
            try:
                msg = r.json().get("error", {}).get("message", "")
            except ValueError:
                msg = r.text[:200]
            raise LLMError(f"Gemini API HTTP {r.status_code}: {msg}")
        raise LLMError(f"Gemini API failed after retries ({last}). Free-tier quota may be exhausted for today.")
