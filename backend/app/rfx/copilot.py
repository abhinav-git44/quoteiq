"""Conversational RFx drafting. The model either asks a question or calls update_rfx_draft
with the FULL draft; the draft is schema-validated and checked deterministically (line count
vs what the buyer asked for, missing pricing basis, duplicate ids) before the UI shows it."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from app.ai.llm import LLMClient, inline_schema, text_of, tool_uses
from app.ai.prompts import RFX_COPILOT_SYSTEM


class DraftLine(BaseModel):
    line_id: str = Field(description="L01, L02, ...")
    item_code: str
    name: str
    description: str
    spec: dict = Field(default_factory=dict, description="kind, length_mm, width_mm, height_mm, ply, board_gsm, bursting_strength_kg_cm2, ...")
    quantity: float = Field(gt=0)
    uom: Literal["pcs", "set", "roll", "kg", "m", "sqm"]
    target_price_inr: Optional[float] = None
    required_delivery_days: Optional[int] = None
    mandatory: bool = True


class DraftQuestion(BaseModel):
    qid: str
    text: str
    type: Literal["yes_no", "number", "text", "attachment"]
    mandatory: bool
    pass_rule: dict = Field(default_factory=dict, description='e.g. {"equals": true} or {"max": 15} or {"min": 40}')


class RfxDraft(BaseModel):
    title: str
    category: str
    description: str
    business_justification: Optional[str] = None
    delivery_location: Optional[str] = None
    submission_deadline: Optional[str] = Field(None, description="YYYY-MM-DD")
    currency: str = "INR"
    required_delivery_days: Optional[int] = None
    payment_terms: Optional[str] = None
    commercial_terms: Optional[str] = Field(None, description="Pricing basis: unit, tax, delivery terms")
    line_items: list[DraftLine] = Field(default_factory=list)
    questionnaire: list[DraftQuestion] = Field(default_factory=list)
    vendor_eligibility_rules: list[str] = Field(default_factory=list)


class CopilotTurn(BaseModel):
    assistant_text: str
    draft: Optional[RfxDraft] = None
    issues: list[str] = Field(default_factory=list)
    messages: list[dict] = Field(default_factory=list)


def requested_line_count(messages: list[dict]) -> Optional[int]:
    for m in reversed(messages):
        if m["role"] == "user" and isinstance(m["content"], str):
            hit = re.search(r"\b(\d{1,3})\s+(?:\w+\s+){0,3}?(?:line items|lines|items|products|skus)\b", m["content"], re.I)
            if hit:
                return int(hit.group(1))
    return None


def check_draft(d: RfxDraft, want: Optional[int]) -> list[str]:
    issues = []
    if want and len(d.line_items) != want:
        issues.append(f"Draft has {len(d.line_items)} line items but {want} were requested — regenerate or complete manually.")
    ids = [l.line_id for l in d.line_items]
    if len(set(ids)) != len(ids):
        issues.append("Duplicate line ids in draft.")
    for l in d.line_items:
        if l.spec.get("kind") in ("rsc", "die_cut", "tray", "sleeve", "pallet_box") and not all(
                l.spec.get(k) for k in ("length_mm", "width_mm", "height_mm", "ply")):
            issues.append(f"{l.line_id}: dimensions/ply incomplete — vendors cannot price it comparably.")
    if not d.commercial_terms:
        issues.append("No pricing basis (unit, tax, delivery terms) — responses will not be comparable.")
    if not any(q.mandatory for q in d.questionnaire):
        issues.append("Questionnaire has no mandatory questions — every vendor would be eligible by default.")
    return issues


def copilot_turn(llm: LLMClient, history: list[dict], user_text: str, current: Optional[RfxDraft] = None) -> CopilotTurn:
    msgs = list(history) + [{"role": "user", "content": user_text + (
        f"\n\n(Current draft JSON for reference:)\n{current.model_dump_json()}" if current else "")}]
    tool = {"name": "update_rfx_draft", "description": "Replace the RFx draft with this full version.",
            "input_schema": inline_schema(RfxDraft.model_json_schema())}
    draft, issues, texts = None, [], []
    for _ in range(3):
        resp = llm.create(system=RFX_COPILOT_SYSTEM, messages=msgs, tools=[tool], max_tokens=16000)
        msgs.append({"role": "assistant", "content": resp.get("content", [])})
        texts.append(text_of(resp))
        uses = tool_uses(resp)
        if not uses:
            break
        results = []
        for u in uses:
            try:
                draft = RfxDraft.model_validate(u["input"])
                issues = check_draft(draft, requested_line_count(msgs))
                results.append({"type": "tool_result", "tool_use_id": u["id"],
                                "content": "Draft saved." + (" Issues: " + " ".join(issues) if issues else "")})
            except ValidationError as e:
                results.append({"type": "tool_result", "tool_use_id": u["id"], "is_error": True,
                                "content": str(e.errors(include_url=False))[:3000]})
        msgs.append({"role": "user", "content": results})
    return CopilotTurn(assistant_text="\n\n".join(t for t in texts if t).strip() or "Draft updated.",
                       draft=draft, issues=issues, messages=msgs)
