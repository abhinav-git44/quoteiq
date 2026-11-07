from app.ai.llm import ScriptedLLM
from app.demo.catalog import QUESTIONNAIRE, rfx_line_items
from app.rfx.copilot import RfxDraft, copilot_turn, requested_line_count


def _draft(n):
    lines = [dict(l, required_delivery_days=15) for l in rfx_line_items()[:n]]
    return {"title": "Corrugated packaging", "category": "Packaging", "description": "x", "currency": "INR",
            "commercial_terms": "INR per UOM ex-GST delivered Chakan", "line_items": lines,
            "questionnaire": QUESTIONNAIRE}


def _tool(payload):
    return {"stop_reason": "tool_use", "content": [{"type": "text", "text": "Here is the draft."},
                                                   {"type": "tool_use", "id": "t1", "name": "update_rfx_draft", "input": payload}]}


def _text(t):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": t}]}


def test_requested_count_detection():
    assert requested_line_count([{"role": "user", "content": "I need 30 corrugated packaging products"}]) == 30
    assert requested_line_count([{"role": "user", "content": "hello"}]) is None


def test_short_draft_is_flagged_not_silently_accepted():
    llm = ScriptedLLM([_tool(_draft(27)), _text("I drafted 27 lines; shall I add 3 more?")])
    t = copilot_turn(llm, [], "I need 30 corrugated packaging products for our Chakan plant")
    assert isinstance(t.draft, RfxDraft) and len(t.draft.line_items) == 27
    assert any("27 line items but 30" in i for i in t.issues)
    assert "Issues:" in llm.calls[1]["messages"][-1]["content"][0]["content"]


def test_full_draft_passes_checks():
    llm = ScriptedLLM([_tool(_draft(30)), _text("Done.")])
    t = copilot_turn(llm, [], "Draft an RFx for 30 corrugated items")
    assert t.issues == [] and len(t.draft.line_items) == 30


def test_invalid_draft_returns_error_to_model():
    bad = _draft(2)
    bad["line_items"][0]["quantity"] = -5
    llm = ScriptedLLM([_tool(bad), _tool(_draft(2)), _text("Fixed.")])
    t = copilot_turn(llm, [], "2 items please")
    assert llm.calls[1]["messages"][-1]["content"][0]["is_error"] is True
    assert t.draft is not None and t.issues == []
