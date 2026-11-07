"""Gemini adapter: schema translation, request/response mapping, retries — with Google's HTTP faked."""
import json

import pytest

from app.ai import gemini as G
from app.ai.gemini import GeminiClient, coerce_json_strings, sanitize_schema
from app.ai.llm import LLMError, get_llm, inline_schema
from app.analyst.agent import run_analyst
from app.analyst.tools import tool_specs
from app.core.config import Settings
from app.demo.catalog import rfx_line_items
from app.domain.extraction import LLMQuotation
from app.extraction.pipeline import extract_quotation
from app.rfx.copilot import RfxDraft
from conftest import parsed
from sim_extraction import DEMO, FILES, simulated_quotation

S = Settings(anthropic_api_key=None, gemini_api_key="g-test", llm_provider="auto", gemini_model="gemini-test")


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._d = status, data
        self.text = json.dumps(data)

    def json(self):
        return self._d


def fc(name, args, sig=None):
    part = {"functionCall": {"name": name, "args": args}}
    if sig:
        part["thoughtSignature"] = sig
    return {"candidates": [{"content": {"role": "model", "parts": [part]}, "finishReason": "STOP"}], "modelVersion": "gemini-test"}


def text(t):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": t}]}, "finishReason": "STOP"}]}


@pytest.fixture
def http(monkeypatch):
    calls, queue = [], []

    def post(url, params=None, json=None, timeout=None):
        calls.append({"url": url, "params": params, "json": json})
        item = queue.pop(0)
        return item if isinstance(item, FakeResp) else FakeResp(200, item)
    monkeypatch.setattr(G.requests, "post", post)
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    return calls, queue


def _walk(node, bad, in_props=False):
    if isinstance(node, dict) and in_props:          # keys here are field names, not schema keywords
        for v in node.values():
            _walk(v, bad)
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "properties":
                _walk(v, bad, in_props=True)
                continue
            if k in ("anyOf", "$ref", "$defs", "title", "additionalProperties", "default", "const"):
                bad.append(k)
            if k == "type" and v == "object" and not node.get("properties"):
                bad.append("empty-object")
            _walk(v, bad)
    elif isinstance(node, list):
        for x in node:
            _walk(x, bad)


def test_provider_selection():
    assert Settings(anthropic_api_key=None, gemini_api_key="g").provider == "gemini"
    assert Settings(anthropic_api_key="a", gemini_api_key="g").provider == "anthropic"
    assert Settings(anthropic_api_key="a", gemini_api_key="g", llm_provider="gemini").provider == "gemini"
    assert Settings(anthropic_api_key=None, gemini_api_key=None).provider is None
    assert isinstance(get_llm(S), GeminiClient)


def test_all_schemas_sanitize_to_gemini_subset():
    schemas = [inline_schema(LLMQuotation.model_json_schema()), inline_schema(RfxDraft.model_json_schema())] + \
              [t["input_schema"] for t in tool_specs()]
    for sc in schemas:
        bad = []
        _walk(sanitize_schema(sc), bad)
        assert bad == [], bad
    out = sanitize_schema(inline_schema(LLMQuotation.model_json_schema()))
    li = out["properties"]["line_items"]["items"]["properties"]
    assert li["price"] == {"type": "number", "description": li["price"]["description"], "nullable": True}
    assert "PIECE" in li["price_uom"]["enum"]


def test_free_form_dicts_round_trip_as_json_strings():
    sc = inline_schema(RfxDraft.model_json_schema())
    args = {"title": "t", "category": "c", "description": "d",
            "line_items": [{"line_id": "L01", "item_code": "X", "name": "n", "description": "d",
                            "spec": '{"ply": 3, "length_mm": 200}', "quantity": 5, "uom": "pcs"}]}
    fixed = coerce_json_strings(args, sc)
    assert RfxDraft.model_validate(fixed).line_items[0].spec == {"ply": 3, "length_mm": 200}


def test_extraction_end_to_end_through_gemini(http):
    calls, queue = http
    payload = simulated_quotation("V-D", parsed("V-D"))
    queue.append(fc("record_quotation", payload, sig="sig-abc"))
    oc = extract_quotation(DEMO / FILES["V-D"], rfx_line_items(), get_llm(S), settings=S)
    assert oc.status == "NEEDS_REVIEW" and oc.model == "gemini-test" and len(oc.lines) == 28
    req = calls[0]["json"]
    assert calls[0]["params"] == {"key": "g-test"} and "gemini-test:generateContent" in calls[0]["url"]
    assert req["toolConfig"]["functionCallingConfig"] == {"mode": "ANY", "allowedFunctionNames": ["record_quotation"]}
    parts = req["contents"][0]["parts"]
    assert "inlineData" in parts[0] and parts[0]["inlineData"]["mimeType"] == "image/png"   # photo sent to vision
    assert "<vendor_document" in parts[1]["text"]
    assert "untrusted" in req["systemInstruction"]["parts"][0]["text"]


def test_validation_retry_sends_function_response_with_signature(http):
    calls, queue = http
    good = simulated_quotation("V-B", parsed("V-B"))
    bad = dict(good)
    bad.pop("header")
    queue += [fc("record_quotation", bad, sig="sig-1"), fc("record_quotation", good)]
    oc = extract_quotation(DEMO / FILES["V-B"], rfx_line_items(), get_llm(S), settings=S)
    assert oc.attempts == 2
    second = calls[1]["json"]["contents"]
    assert [c["role"] for c in second] == ["user", "model", "user"]
    assert second[1]["parts"][0]["thoughtSignature"] == "sig-1"            # signature preserved
    fr = second[2]["parts"][0]["functionResponse"]
    assert fr["name"] == "record_quotation" and "error" in fr["response"]


def test_analyst_loop_through_gemini(http, ctx):
    calls, queue = http

    def answer():
        return text("Placeholder")
    queue += [fc("optimize_split_award", {"strategy": "LOWEST_PRICE_SPLIT"}), answer()]
    turn = run_analyst(ctx, get_llm(S), "Split it among qualified vendors?")
    assert turn.tool_calls[0].ok and turn.tool_calls[0].name == "optimize_split_award"
    assert turn.answer == "Placeholder" and turn.displays
    second = calls[1]["json"]
    fr = second["contents"][-1]["parts"][0]["functionResponse"]
    assert fr["name"] == "optimize_split_award" and "net_total" in fr["response"]
    assert second["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"
    assert len(second["tools"][0]["functionDeclarations"]) == len(tool_specs())


def test_rate_limit_retry_then_success(http):
    calls, queue = http
    queue += [FakeResp(429, {"error": {"details": [{"retryDelay": "7s"}]}}), text("ok")]
    out = get_llm(S).create(system="s", messages=[{"role": "user", "content": "hi"}])
    assert out["content"][0]["text"] == "ok" and len(calls) == 2


def test_errors_are_reported(http):
    calls, queue = http
    queue.append(FakeResp(400, {"error": {"message": "API key not valid"}}))
    with pytest.raises(LLMError, match="API key not valid"):
        get_llm(S).create(system="s", messages=[{"role": "user", "content": "hi"}])
    queue.append({"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(LLMError, match="SAFETY"):
        get_llm(S).create(system="s", messages=[{"role": "user", "content": "hi"}])
