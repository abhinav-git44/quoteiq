import copy

from app.ai.llm import LLMError, ScriptedLLM
from app.core.config import Settings
from app.demo.catalog import rfx_line_items
from app.extraction.pipeline import extract_quotation
from conftest import parsed
from sim_extraction import DEMO, FILES, simulated_quotation, tool_response


def test_ai_unavailable_shows_parsed_text_and_extracts_nothing():
    oc = extract_quotation(DEMO / FILES["V-A"], rfx_line_items(), llm=None, settings=Settings(anthropic_api_key=None))
    assert oc.status == "AI_UNAVAILABLE"
    assert oc.document and oc.document.segments
    assert oc.lines == [] and oc.quotation is None


def test_schema_failure_is_retried_with_errors_then_succeeds():
    good = simulated_quotation("V-B", parsed("V-B"))
    bad = copy.deepcopy(good)
    del bad["header"]
    llm = ScriptedLLM([tool_response(bad), tool_response(good)])
    oc = extract_quotation(DEMO / FILES["V-B"], rfx_line_items(), llm, settings=Settings(anthropic_api_key="x"))
    assert oc.attempts == 2 and oc.status in ("SUCCEEDED", "NEEDS_REVIEW")
    retry_msg = llm.calls[1]["messages"][-1]["content"][0]
    assert retry_msg["type"] == "tool_result" and retry_msg["is_error"] and "header" in retry_msg["content"]
    assert oc.coverage["L13"] == "NOT_QUOTED"


def test_prompt_wraps_document_as_untrusted_and_lists_rfx_lines():
    good = simulated_quotation("V-C", parsed("V-C"))
    llm = ScriptedLLM([tool_response(good)])
    extract_quotation(DEMO / FILES["V-C"], rfx_line_items(), llm, settings=Settings(anthropic_api_key="x"))
    call = llm.calls[0]
    text = call["messages"][0]["content"][-1]["text"]
    assert "<vendor_document" in text and "L30 |" in text
    assert "untrusted" in call["system"].lower()
    assert call["tool_choice"] == {"type": "tool", "name": "record_quotation"}
    assert "$ref" not in str(call["tools"][0]["input_schema"])


def test_photo_sends_image_to_vision_model():
    good = simulated_quotation("V-D", parsed("V-D"))
    llm = ScriptedLLM([tool_response(good)])
    oc = extract_quotation(DEMO / FILES["V-D"], rfx_line_items(), llm, settings=Settings(anthropic_api_key="x"))
    assert llm.calls[0]["messages"][0]["content"][0]["type"] == "image"
    assert oc.status == "NEEDS_REVIEW"


def test_persistent_failure_is_reported_not_hidden():
    bad = {"header": {}}
    llm = ScriptedLLM([tool_response(bad)] * 3)
    oc = extract_quotation(DEMO / FILES["V-A"], rfx_line_items(), llm, settings=Settings(anthropic_api_key="x"))
    assert oc.status == "FAILED" and "validation" in oc.error


def test_api_error_becomes_failed_state():
    def boom(*a):
        raise LLMError("Anthropic API HTTP 401: invalid x-api-key")
    oc = extract_quotation(DEMO / FILES["V-A"], rfx_line_items(), ScriptedLLM([boom]), settings=Settings(anthropic_api_key="x"))
    assert oc.status == "FAILED" and "401" in oc.error
