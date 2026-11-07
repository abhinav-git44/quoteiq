import json

from openpyxl import load_workbook

from app.ai.llm import ScriptedLLM
from app.analyst.agent import grounding_check, run_analyst
from app.analyst.tools import TOOLS, run_tool, tool_specs


def test_every_tool_has_valid_schema_and_runs(ctx):
    specs = tool_specs()
    assert len(specs) == len(TOOLS) >= 14
    sample = {
        "get_vendor_quotation_details": {"vendor_id": "Vendor E", "line_ids": ["L05"], "include_trace": True},
        "calculate_normalized_cost": {"vendor_id": "V-E", "line_id": "L05", "fx_rate_override": 90},
        "calculate_savings": None, "create_export_report": {"kind": "comparison_xlsx"},
        "draft_vendor_clarification": {"vendor_id": "V-E"}, "generate_chart_data": {"chart": "coverage"},
    }
    sid = run_tool(ctx, "optimize_split_award", {})["result"]["scenario_id"]
    sample["calculate_savings"] = {"scenario_id": sid}
    for name in TOOLS:
        out = run_tool(ctx, name, sample.get(name, {}))
        json.dumps(out["result"], default=str)


def test_tool_input_validation_errors(ctx):
    import pytest
    from pydantic import ValidationError
    from app.analyst.tools import ToolError
    with pytest.raises(ValidationError):
        run_tool(ctx, "optimize_split_award", {"max_vendors": 0})
    with pytest.raises(ToolError):
        run_tool(ctx, "calculate_savings", {"scenario_id": "SCN-NOPE"})
    with pytest.raises(ToolError):
        run_tool(ctx, "nope", {})


def test_vp_question_answer_is_tool_derived(ctx):
    res = run_tool(ctx, "optimize_split_award", {"strategy": "LOWEST_PRICE_SPLIT", "eligible_only": True})["result"]
    assert set(res["eligible_vendors"]) == {"V-A", "V-B", "V-E"}
    assert res["lines_unallocated"] == 0


def _tool_use(name, args, id_="t1"):
    return {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": id_, "name": name, "input": args}]}


def _text(t):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": t}]}


def test_agent_loop_executes_tools_and_flags_ungrounded_numbers(ctx):
    def answer(system, messages, tools):
        res = json.loads(messages[-1]["content"][0]["content"])
        return _text(f"Split nets ₹{res['net_total']:,.0f} across {res['lines_allocated']} lines; "
                     f"it also saves ₹12,34,567 (made up).")
    llm = ScriptedLLM([_tool_use("optimize_split_award", {"strategy": "LOWEST_PRICE_SPLIT"}), answer])
    turn = run_analyst(ctx, llm, "What if we split it, cheapest per line, only among vendors who cleared quality?")
    assert turn.tool_calls[0].ok and turn.displays
    assert turn.grounded_number_count >= 1
    assert turn.ungrounded_numbers == ["12,34,567"]
    assert len(llm.calls[0]["tools"]) == len(TOOLS)


def test_agent_returns_tool_errors_to_model(ctx):
    llm = ScriptedLLM([_tool_use("calculate_savings", {"scenario_id": "SCN-X"}), _text("I need to build a scenario first.")])
    turn = run_analyst(ctx, llm, "savings?")
    assert not turn.tool_calls[0].ok
    tr = llm.calls[1]["messages"][-1]["content"][0]
    assert tr["is_error"] is True


def test_agent_step_limit(ctx):
    llm = ScriptedLLM([_tool_use("get_rfx_summary", {}, f"t{i}") for i in range(12)])
    turn = run_analyst(ctx, llm, "loop forever")
    assert turn.stopped_reason == "max_steps" and "step limit" in turn.answer


def test_grounding_check_formats():
    tools = [{"net_total": 27318288.0, "savings_pct": 6.68, "savings": 1955841.5}]
    bad, good = grounding_check("Net ₹2.73 crore (₹2,73,18,288), saving ₹19.6 lakh or 6.68% on L05 across 30 lines.", tools)
    assert bad == [] and good >= 4
    bad, _ = grounding_check("Saving ₹21.4 lakh.", tools)
    assert bad == ["21.4 lakh"]


def test_exports(ctx, tmp_path):
    from app.reporting import exports as X
    p = X.comparison_xlsx(ctx, tmp_path / "c.xlsx")
    wb = load_workbook(p)
    assert wb.sheetnames == ["Comparison (normalized)", "Original quotes", "Coverage & terms", "Assumptions & policy"]
    ws = wb["Comparison (normalized)"]
    assert ws["A5"].value == "L01" and ws.max_row == 34
    sid = run_tool(ctx, "optimize_split_award", {})["result"]["scenario_id"]
    pdf = X.award_pdf(ctx, ctx.scenarios[sid], tmp_path / "a.pdf", baseline=None)
    assert pdf.read_bytes()[:4] == b"%PDF"
    assert X.quality_pdf(ctx, tmp_path / "q.pdf").exists()
    assert X.exceptions_xlsx(ctx, tmp_path / "e.xlsx").exists()
