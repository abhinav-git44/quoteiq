"""Claude tool-use loop for the procurement analyst + a numeric grounding check.

After the model answers, every number in the answer is checked against the numbers that
tools actually returned in this turn (allowing ₹ lakh/crore and percentage formatting).
Numbers that cannot be traced are returned to the UI and highlighted, not hidden.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from app.ai.llm import LLMClient, text_of, tool_uses
from app.ai.prompts import ANALYST_SYSTEM
from app.analyst.context import AnalysisContext
from app.analyst.tools import ToolError, run_tool, tool_specs

log = logging.getLogger("quoteiq.analyst")
MAX_STEPS = 10
MAX_TOOL_CHARS = 14000


class ToolCallRecord(BaseModel):
    id: str
    name: str
    input: dict[str, Any]
    ok: bool
    error: Optional[str] = None
    ms: int = 0
    result: Any = None


class AnalystTurn(BaseModel):
    question: str
    answer: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    displays: list[dict[str, Any]] = Field(default_factory=list)
    ungrounded_numbers: list[str] = Field(default_factory=list)
    grounded_number_count: int = 0
    messages: list[dict[str, Any]] = Field(default_factory=list)   # full API transcript for persistence
    stopped_reason: str = "end_turn"
    model: Optional[str] = None


# ------------------------------------------------------------------ number grounding
_ANS_NUM = re.compile(r"(?<![A-Za-z\d])(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)(\s*(?:%|lakh|lac|crore|cr\b|L\b|k\b))?", re.I)


def _collect(obj, out: set):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj)); return
    if isinstance(obj, str):
        for m in re.findall(r"\d[\d,]*(?:\.\d+)?", obj):
            try:
                out.add(float(m.replace(",", "")))
            except ValueError:
                pass
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _collect(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, out)


def _variants(xs: set[float]) -> set[float]:
    out = set()
    for x in xs:
        for v in (x, x / 1e5, x / 1e7, x * 100, x / 1000):
            for d in (0, 1, 2, 3, 4):
                out.add(round(v, d))
    return out


def grounding_check(answer: str, tool_results: list[Any], question: str = "") -> tuple[list[str], int]:
    raw: set[float] = set()
    for r in tool_results:
        _collect(r, raw)
    _collect(question, raw)
    allowed = _variants(raw)
    bad, good = [], 0
    for m in _ANS_NUM.finditer(answer):
        tok, unit = m.group(1), (m.group(2) or "").strip().lower()
        start = m.start()
        if start > 0 and answer[start - 1] in "LlVv-" and re.match(r"[LV]-?\d", answer[start - 1:start + 3] or ""):
            continue  # line / vendor ids like L05, V-A
        try:
            val = float(tok.replace(",", ""))
        except ValueError:
            continue
        if not unit and val.is_integer() and (val <= 31 or 2020 <= val <= 2035):
            continue  # small counts, days, ply, years
        cands = {val}
        if unit in ("lakh", "lac", "l"):
            cands |= {val, val * 1e5}
        elif unit in ("crore", "cr"):
            cands |= {val, val * 1e7}
        elif unit == "k":
            cands |= {val * 1000}
        ok = any(c in allowed for c in cands) or any(
            abs(c - a) <= max(0.0051, abs(a) * 0.0015) for c in cands for a in raw if a)
        if ok:
            good += 1
        else:
            bad.append(m.group(0).strip())
    return bad, good


# ------------------------------------------------------------------ agent loop
def _trim_history(history: list[dict], keep_turns: int = 6) -> list[dict]:
    """Keep the last N user questions; replace old tool results with a stub to bound context."""
    user_idx = [i for i, m in enumerate(history) if m["role"] == "user" and isinstance(m["content"], str)]
    start = user_idx[-keep_turns] if len(user_idx) > keep_turns else 0
    trimmed = history[start:]
    cut = user_idx[-2] if len(user_idx) >= 2 else 0
    out = []
    for i, m in enumerate(trimmed):
        if start + i < cut and m["role"] == "user" and isinstance(m["content"], list):
            m = {"role": "user", "content": [
                {**b, "content": "(earlier tool result omitted; call the tool again if needed)"} if b.get("type") == "tool_result" else b
                for b in m["content"]]}
        out.append(m)
    return out


def run_analyst(ctx: AnalysisContext, llm: LLMClient, question: str, history: Optional[list[dict]] = None) -> AnalystTurn:
    msgs = _trim_history(list(history or []))
    msgs.append({"role": "user", "content": question})
    tools = tool_specs()
    calls: list[ToolCallRecord] = []
    displays: list[dict] = []
    results_for_grounding: list[Any] = []
    system = ANALYST_SYSTEM + f"\n\nContext: RFx {ctx.rfx.get('reference')} — {ctx.rfx.get('title')}. " \
                              f"Vendors: " + ", ".join(f"{v['vendor_id']} {v['name']}" for v in ctx.vendors) + \
             f". Base currency {ctx.settings.base_currency}."
    stopped = "end_turn"
    for step in range(MAX_STEPS):
        resp = llm.create(system=system, messages=msgs, tools=tools, max_tokens=4096)
        content = resp.get("content", [])
        msgs.append({"role": "assistant", "content": content})
        uses = tool_uses(resp)
        if not uses:
            stopped = resp.get("stop_reason", "end_turn")
            break
        results = []
        for u in uses:
            t0 = time.time()
            rec = ToolCallRecord(id=u["id"], name=u["name"], input=u.get("input") or {}, ok=True)
            try:
                out = run_tool(ctx, u["name"], u.get("input") or {})
                rec.result = out["result"]
                displays.extend(out.get("displays", []))
                results_for_grounding.append(out["result"])
                payload = json.dumps(out["result"], default=str)
                if len(payload) > MAX_TOOL_CHARS:
                    payload = payload[:MAX_TOOL_CHARS] + '... (truncated; narrow the query with line_ids/vendor_ids)'
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": payload})
            except (ToolError, ValidationError) as e:
                rec.ok, rec.error = False, str(e)[:500]
                results.append({"type": "tool_result", "tool_use_id": u["id"], "is_error": True, "content": rec.error})
            except Exception:  # never leak stack traces to the model
                log.exception("Tool %s failed", u["name"])
                rec.ok, rec.error = False, f"Internal error in {u['name']}"
                results.append({"type": "tool_result", "tool_use_id": u["id"], "is_error": True, "content": rec.error})
            rec.ms = int((time.time() - t0) * 1000)
            calls.append(rec)
        msgs.append({"role": "user", "content": results})
    else:
        stopped = "max_steps"
    answer = text_of({"content": msgs[-1]["content"]}) if msgs[-1]["role"] == "assistant" else ""
    if not answer:
        answer = ("I couldn't complete the analysis within the step limit. The tool results gathered so far are shown below."
                  if stopped == "max_steps" else "(no answer)")
    bad, good = grounding_check(answer, results_for_grounding, question)
    return AnalystTurn(question=question, answer=answer, tool_calls=calls, displays=displays, ungrounded_numbers=bad,
                       grounded_number_count=good, messages=msgs, stopped_reason=stopped, model=getattr(llm, "model", None))
