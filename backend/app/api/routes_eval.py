"""Comparison, review, quality, analyst, award scenarios, reports, audit."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm import LLMError, get_llm
from app.analyst.agent import run_analyst
from app.analyst.tools import ExceptionArgs, get_extraction_exceptions, run_tool
from app.api.deps import current_user, rfx_for
from app.db.models import (AnalystConversation, AnalystMessage, AuditLog, AwardScenario, FieldReview,
                           ReportExport, User, VendorQuestionnaireAnswer)
from app.db.session import get_db
from app.optimization.award import AwardParams, build_scenario
from app.services.common import audit
from app.services.rfx_service import build_rfx_context, create_export, persist_scenario, snapshot_normalized

router = APIRouter(prefix="/api")


def _q(q):
    return {"status": q.status, "unit": q.unit_price_base, "landed": q.landed_unit_price, "value": q.line_value_base,
            "orig": q.original_price, "ccy": q.original_currency, "uom": q.original_uom, "basis": q.price_basis_text,
            "conv": q.conversion_kind, "conf": round(q.confidence), "review": q.review_required, "reason": q.reason,
            "flags": q.flags, "offers": q.conditional_offers}


@router.get("/rfx/{rfx_id}/comparison")
def comparison(rfx_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    ctx = build_rfx_context(db, rfx_id, user.id)
    vendors = []
    for vs in ctx.norm.vendors:
        el = ctx.eligibility[vs.vendor_id]
        lowest = 0
        for l in ctx.lines:
            c = [q for q in ctx.norm.quotes if q.rfx_line_id == l["line_id"] and q.comparable]
            if c and min(c, key=lambda q: q.unit_price_base).vendor_id == vs.vendor_id:
                lowest += 1
        vendors.append({**vs.model_dump(mode="json"), "quality_status": el.status, "quality_score": el.quality_score,
                        "quality_reasons": el.reasons, "lowest_lines": lowest,
                        "extraction_status": ctx.extraction.get(vs.vendor_id, {}).get("status"),
                        "document_id": ctx.extraction.get(vs.vendor_id, {}).get("document_id"),
                        "total_own_comparable": round(sum(q.line_value_base for q in ctx.norm.quotes
                                                          if q.vendor_id == vs.vendor_id and q.comparable), 2),
                        "exceptions": len(ctx.extraction.get(vs.vendor_id, {}).get("exceptions", []))})
    lines = []
    for l in ctx.lines:
        lines.append({**l, "quotes": {v["vendor_id"]: _q(ctx.norm.get(v["vendor_id"], l["line_id"]))
                                      for v in ctx.vendors if ctx.norm.get(v["vendor_id"], l["line_id"])}})
    return {"rfx": ctx.rfx, "vendors": vendors, "lines": lines, "policy": ctx.norm.policy, "fx": ctx.fx_rates,
            "submitted_vendor_ids": [v.vendor_id for v in ctx.norm.vendors]}


@router.get("/rfx/{rfx_id}/quotes/{vendor_id}/{line_id}")
def quote_detail(rfx_id: str, vendor_id: str, line_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    ctx = build_rfx_context(db, rfx_id, user.id)
    q = ctx.norm.get(vendor_id, line_id.upper())
    if not q:
        raise HTTPException(404, "No quote for this vendor/line")
    checks = []
    oc_doc = ctx.extraction.get(vendor_id, {}).get("document_id")
    vi = next((v for v in ctx.vendor_inputs if v.vendor_id == vendor_id), None)
    li = next((l for l in (vi.lines if vi else []) if l.rfx_line_id == line_id.upper()), None)
    if oc_doc:
        from app.db.models import ExtractionResult
        res = db.scalar(select(ExtractionResult).where(ExtractionResult.document_id == oc_doc).order_by(ExtractionResult.created_at.desc()))
        for vl in (res.outcome.get("lines", []) if res else []):
            if vl["llm"].get("rfx_line_id") == line_id.upper():
                checks = vl["checks"]
                break
    history = [{"action": f.action, "before": f.before, "after": f.after, "comment": f.comment, "at": f.created_at}
               for f in db.scalars(select(FieldReview).where(FieldReview.rfx_id == rfx_id, FieldReview.vendor_id == vendor_id,
                                                             FieldReview.rfx_line_id == line_id.upper()).order_by(FieldReview.created_at))]
    return {"quote": q.model_dump(mode="json"), "line": ctx.line(line_id), "vendor": ctx.names.get(vendor_id),
            "document_id": oc_doc, "checks": checks, "review_history": history,
            "input": li.model_dump(mode="json") if li else None}


@router.get("/rfx/{rfx_id}/exceptions")
def exceptions(rfx_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    ctx = build_rfx_context(db, rfx_id, user.id)
    out = get_extraction_exceptions(ctx, ExceptionArgs())
    return {"items": out["result"]["items"], "document_ids": {v: x.get("document_id") for v, x in ctx.extraction.items()}}


@router.get("/rfx/{rfx_id}/quality")
def quality(rfx_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    ctx = build_rfx_context(db, rfx_id, user.id)
    return {"policy": "Eligible only if every mandatory question passes; missing mandatory answers stay PENDING.",
            "questionnaire": ctx.questionnaire,
            "vendors": [{"vendor_id": v["vendor_id"], "name": v["name"], **ctx.eligibility[v["vendor_id"]].model_dump(mode="json")}
                        for v in ctx.vendors]}


class ReviewIn(BaseModel):
    vendor_id: str
    line_id: str
    action: Literal["CONFIRM", "CORRECT", "ACCEPT_ASSUMPTION", "MARK_NOT_QUOTED", "MARK_NEEDS_CLARIFICATION"]
    after: Optional[dict[str, Any]] = None
    comment: Optional[str] = None


@router.post("/rfx/{rfx_id}/reviews")
def review(rfx_id: str, body: ReviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    if body.action == "CORRECT":
        allowed = {"price", "price_uom", "units_per_price_uom", "currency", "line_discount_pct"}
        if not body.after or not set(body.after) <= allowed:
            raise HTTPException(422, f"CORRECT needs 'after' with any of {sorted(allowed)}")
        if "price" in body.after and (body.after["price"] is None or float(body.after["price"]) <= 0):
            raise HTTPException(422, "Price must be positive")
        if not body.comment:
            raise HTTPException(422, "A comment is required when correcting an extracted value")
    ctx = build_rfx_context(db, rfx_id, user.id)
    before_q = ctx.norm.get(body.vendor_id, body.line_id.upper())
    fr = FieldReview(rfx_id=rfx_id, vendor_id=body.vendor_id, rfx_line_id=body.line_id.upper(), action=body.action,
                     before=_q(before_q) if before_q else None, after=body.after, comment=body.comment, user_id=user.id)
    db.add(fr); db.flush()
    audit(db, "EXTRACTION_REVIEWED" if body.action != "CORRECT" else "EXTRACTION_CORRECTED", "quote",
          f"{body.vendor_id}:{body.line_id.upper()}", user.id, before=fr.before, after={"action": body.action, **(body.after or {})},
          meta={"comment": body.comment})
    snapshot_normalized(db, rfx_id)
    ctx = build_rfx_context(db, rfx_id, user.id)
    after_q = ctx.norm.get(body.vendor_id, body.line_id.upper())
    return {"quote": after_q.model_dump(mode="json") if after_q else None}


class QOverrideIn(BaseModel):
    status: Literal["PASS", "FAIL", "PENDING", "NOT_APPLICABLE", "NEEDS_REVIEW"]
    comment: str


@router.post("/rfx/{rfx_id}/questionnaire/{vendor_id}/{qid}/override")
def q_override(rfx_id: str, vendor_id: str, qid: str, body: QOverrideIn, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    a = db.scalar(select(VendorQuestionnaireAnswer).where(VendorQuestionnaireAnswer.rfx_id == rfx_id,
                                                          VendorQuestionnaireAnswer.vendor_id == vendor_id,
                                                          VendorQuestionnaireAnswer.qid == qid))
    if not a:
        a = VendorQuestionnaireAnswer(rfx_id=rfx_id, vendor_id=vendor_id, qid=qid, answer=None)
        db.add(a)
    before = {"status": a.reviewer_status}
    a.reviewer_status, a.reviewer_comment, a.reviewed_by, a.reviewed_at = body.status, body.comment, user.id, datetime.now(timezone.utc)
    audit(db, "QUESTIONNAIRE_EVALUATED", "questionnaire_answer", f"{vendor_id}:{qid}", user.id, before=before,
          after={"status": body.status, "comment": body.comment})
    return {"ok": True}


# ------------------------------------------------------------------ analyst
class ChatIn(BaseModel):
    question: str
    conversation_id: Optional[str] = None


@router.post("/rfx/{rfx_id}/analyst/chat")
def chat(rfx_id: str, body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    llm = get_llm()
    if llm is None:
        raise HTTPException(503, "AI analyst unavailable: ANTHROPIC_API_KEY is not configured. "
                                 "The comparison and award pages still work (deterministic).")
    if not body.question.strip() or len(body.question) > 4000:
        raise HTTPException(422, "Question must be 1–4000 characters")
    conv = db.get(AnalystConversation, body.conversation_id) if body.conversation_id else None
    if conv is None:
        conv = AnalystConversation(rfx_id=rfx_id, user_id=user.id, title=body.question[:120], transcript=[])
        db.add(conv); db.flush()
    ctx = build_rfx_context(db, rfx_id, user.id)
    try:
        turn = run_analyst(ctx, llm, body.question, conv.transcript or [])
    except LLMError as e:
        raise HTTPException(502, f"AI service error: {e}")
    conv.transcript = turn.messages
    db.add(AnalystMessage(conversation_id=conv.id, role="user", content=body.question))
    msg = AnalystMessage(conversation_id=conv.id, role="assistant", content=turn.answer,
                         tool_calls=[c.model_dump(mode="json") for c in turn.tool_calls], displays=turn.displays,
                         ungrounded_numbers=turn.ungrounded_numbers, model=turn.model)
    db.add(msg); db.flush()
    audit(db, "ANALYST_QUESTION", "analyst_conversation", conv.id, user.id,
          meta={"question": body.question[:500], "tools": [c.name for c in turn.tool_calls],
                "ungrounded_numbers": turn.ungrounded_numbers})
    return {"conversation_id": conv.id, "message": _msg(msg)}


def _msg(m: AnalystMessage):
    return {"id": m.id, "role": m.role, "content": m.content, "tool_calls": m.tool_calls, "displays": m.displays,
            "ungrounded_numbers": m.ungrounded_numbers, "model": m.model, "created_at": m.created_at}


@router.get("/rfx/{rfx_id}/analyst/conversations")
def conversations(rfx_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    return [{"id": c.id, "title": c.title, "created_at": c.created_at}
            for c in db.scalars(select(AnalystConversation).where(AnalystConversation.rfx_id == rfx_id)
                                .order_by(AnalystConversation.created_at.desc()))]


@router.get("/analyst/conversations/{cid}")
def conversation(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(AnalystConversation, cid)
    if not c:
        raise HTTPException(404, "Conversation not found")
    rfx_for(c.rfx_id, user, db)
    return {"id": c.id, "title": c.title, "messages": [_msg(m) for m in c.messages]}


@router.get("/rfx/{rfx_id}/analyst/suggestions")
def suggestions(rfx_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    ctx = build_rfx_context(db, rfx_id, user.id)
    s = ["Who is the cheapest vendor overall — and is that a fair comparison?",
         "What if we split it, cheapest per line, but only among vendors who cleared the quality questionnaire?"]
    if any(v.coverage_pct < 100 for v in ctx.norm.vendors):
        s.append("Which vendors quoted fewer than 30 items, and why?")
    if any(v.review_required_lines for v in ctx.norm.vendors):
        s.append("Which numbers are you not sure about, and do any of them change the award?")
    if any(v.freight_basis != "INCLUDED" for v in ctx.norm.vendors):
        s.append("What happens to the ranking if freight is included?")
    if any(v.conditional_discounts for v in ctx.norm.vendors):
        s.append("Are there discounts we only get under certain conditions? Is it worth meeting them?")
    if any(e.status != "ELIGIBLE" for e in ctx.eligibility.values()):
        s.append("What is excluding the cheapest vendor costing us?")
    s += ["Recommend an award strategy with risks and alternatives.", "Draft a clarification email to GlobalPack."]
    return s[:8]


# ------------------------------------------------------------------ award
@router.post("/rfx/{rfx_id}/award/optimize")
def optimize(rfx_id: str, params: AwardParams, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    ctx = build_rfx_context(db, rfx_id, user.id)
    s = build_scenario(ctx.norm, ctx.eligibility, ctx.lines, {v["vendor_id"]: v for v in ctx.vendors}, params,
                       ctx.rfx.get("required_delivery_days") or 15)
    persist_scenario(db, rfx_id, s, user.id)
    return s.model_dump(mode="json")


@router.get("/rfx/{rfx_id}/award/scenarios")
def scenarios(rfx_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    return [{"scenario_id": s.scenario_id, "name": s.name, "strategy": s.strategy, "net_total": s.net_total,
             "gross_total": s.gross_total, "lines_allocated": s.lines_allocated, "lines_unallocated": s.lines_unallocated,
             "status": s.status, "approved_by": s.approved_by, "approved_at": s.approved_at, "created_at": s.created_at,
             "vendors_used": len(s.data.get("vendor_shares", [])),
             "review_lines": sum(1 for a in s.data.get("allocations", []) if a.get("review_required"))}
            for s in db.scalars(select(AwardScenario).where(AwardScenario.rfx_id == rfx_id).order_by(AwardScenario.created_at))]


@router.get("/rfx/{rfx_id}/award/scenarios/{sid}")
def scenario(rfx_id: str, sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    row = db.scalar(select(AwardScenario).where(AwardScenario.rfx_id == rfx_id, AwardScenario.scenario_id == sid))
    if not row:
        raise HTTPException(404, "Scenario not found")
    return {**row.data, "status": row.status, "approved_by": row.approved_by, "approved_at": row.approved_at,
            "approval_comment": row.approval_comment}


@router.get("/rfx/{rfx_id}/award/scenarios/{sid}/savings")
def savings(rfx_id: str, sid: str, baseline: str = "best_single_vendor", user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    ctx = build_rfx_context(db, rfx_id, user.id)
    if sid not in ctx.scenarios:
        raise HTTPException(404, "Scenario not found")
    return run_tool(ctx, "calculate_savings", {"scenario_id": sid, "baseline": baseline})["result"]


class ApproveIn(BaseModel):
    comment: str
    acknowledge_unallocated: bool = False


@router.post("/rfx/{rfx_id}/award/scenarios/{sid}/approve")
def approve(rfx_id: str, sid: str, body: ApproveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Human approval. Blocked while any awarded value is unverified — the system will not let an award
    rest on a number nobody has checked."""
    r = rfx_for(rfx_id, user, db)
    row = db.scalar(select(AwardScenario).where(AwardScenario.rfx_id == rfx_id, AwardScenario.scenario_id == sid))
    if not row:
        raise HTTPException(404, "Scenario not found")
    ctx = build_rfx_context(db, rfx_id, user.id)
    fresh = build_scenario(ctx.norm, ctx.eligibility, ctx.lines, {v["vendor_id"]: v for v in ctx.vendors},
                           AwardParams.model_validate(row.params), ctx.rfx.get("required_delivery_days") or 15)
    unverified = [a.line_id for a in fresh.allocations if a.review_required]
    if unverified:
        raise HTTPException(409, {"message": "Award rests on values awaiting verification. Verify or correct them first.",
                                  "lines": unverified})
    if fresh.lines_unallocated and not body.acknowledge_unallocated:
        raise HTTPException(409, {"message": f"{fresh.lines_unallocated} line(s) are unallocated. Acknowledge to approve a partial award.",
                                  "lines": [u["line_id"] for u in fresh.unallocated]})
    if abs(fresh.net_total - row.net_total) > 0.5:
        persist_scenario(db, rfx_id, fresh, user.id)   # data changed since generation: approve the recomputed numbers
    for other in db.scalars(select(AwardScenario).where(AwardScenario.rfx_id == rfx_id, AwardScenario.status == "APPROVED")):
        other.status = "SUPERSEDED"
    row.status, row.approved_by, row.approved_at, row.approval_comment = "APPROVED", user.id, datetime.now(timezone.utc), body.comment
    r.status = "AWARDED"
    audit(db, "AWARD_APPROVED", "award_scenario", sid, user.id, after={"net_total": fresh.net_total, "comment": body.comment})
    return {"ok": True, "status": "APPROVED", "net_total": fresh.net_total}


# ------------------------------------------------------------------ reports & audit
class ReportIn(BaseModel):
    kind: Literal["comparison_xlsx", "award_pdf", "exceptions_xlsx", "quality_pdf", "audit_csv"]
    scenario_id: Optional[str] = None


@router.post("/rfx/{rfx_id}/reports")
def report(rfx_id: str, body: ReportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfx_for(rfx_id, user, db)
    ctx = build_rfx_context(db, rfx_id, user.id)
    if body.kind == "award_pdf" and body.scenario_id not in ctx.scenarios:
        raise HTTPException(422, "award_pdf requires an existing scenario_id")
    return create_export(db, ctx, rfx_id, body.kind, body.scenario_id, user.id)


@router.get("/reports")
def reports(rfx_id: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(ReportExport).order_by(ReportExport.created_at.desc())
    if rfx_id:
        rfx_for(rfx_id, user, db)
        q = q.where(ReportExport.rfx_id == rfx_id)
    return [{"id": r.id, "rfx_id": r.rfx_id, "kind": r.kind, "scenario_id": r.scenario_id, "filename": r.filename,
             "created_at": r.created_at, "download_url": f"/api/reports/{r.id}/download"} for r in db.scalars(q).all()[:200]]


@router.get("/reports/{rid}/download")
def download(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(ReportExport, rid)
    if not r:
        raise HTTPException(404, "Report not found")
    rfx_for(r.rfx_id, user, db)
    p = Path(r.stored_path)
    if not p.exists():
        raise HTTPException(404, "File missing")
    return FileResponse(p, filename=r.filename)


@router.get("/audit-logs")
def audit_logs(limit: int = 200, action: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 1000))
    if action:
        q = q.where(AuditLog.action == action)
    users = {u.id: u.name for u in db.scalars(select(User))}
    return [{"id": a.id, "at": a.created_at, "user": users.get(a.user_id, "system"), "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "document_id": a.document_id,
             "before": a.before, "after": a.after, "meta": a.meta} for a in db.scalars(q)]
