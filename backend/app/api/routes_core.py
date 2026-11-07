"""Auth, dashboard, RFx (incl. co-pilot), vendors, submissions, documents, extraction jobs."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.llm import LLMError, get_llm
from app.api.deps import current_user, rfx_for
from app.core.config import get_settings
from app.db.models import (Document, ExtractionJob, ExtractionResult, FieldReview, QuestionnaireQuestion, Rfx, RfxLineItem,
                           RfxTerm, RfxVendor, SourceEvidence, Submission, User, Vendor)
from app.db.session import get_db
from app.extraction.parsers import UnsupportedDocument
from app.rfx.copilot import RfxDraft, check_draft, copilot_turn
from app.services.common import audit, make_token, verify_password
from app.services.rfx_service import (build_rfx_context, line_dict, queue_extraction, register_document, rfx_dict,
                                      run_job, vendor_dict)

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    audit(db, "USER_LOGIN", "user", u.id, u.id)
    return {"token": make_token(u.id), "user": {"id": u.id, "name": u.name, "email": u.email, "role": u.role}}


@router.post("/auth/logout")
def logout(user: User = Depends(current_user)):
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    s = get_settings()
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role,
            "ai_enabled": s.ai_enabled, "provider": s.provider, "model": s.active_model}


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rfxs = db.scalars(select(Rfx).where(Rfx.org_id == user.org_id).order_by(Rfx.created_at.desc())).all()
    out = {"ai_enabled": get_settings().ai_enabled, "rfx": [], "kpis": {}}
    jobs = db.execute(select(ExtractionJob.status, func.count()).join(Document).where(Document.kind == "QUOTATION")
                      .group_by(ExtractionJob.status)).all()
    js = dict(jobs)
    done = sum(js.get(k, 0) for k in ("SUCCEEDED", "NEEDS_REVIEW"))
    total = sum(js.values())
    out["kpis"]["extraction"] = {"by_status": js, "success_rate": round(100 * done / total, 1) if total else None}
    for r in rfxs:
        item = {**rfx_dict(r), "line_count": len(r.lines)}
        if r.status in ("EVALUATION", "PUBLISHED", "AWARDED"):
            try:
                ctx = build_rfx_context(db, r.id, user.id)
                vs = ctx.norm.vendors
                item["vendors"] = [{"vendor_id": v.vendor_id, "name": v.vendor_name, "coverage_pct": v.coverage_pct,
                                    "review": v.review_required_lines, "status": ctx.extraction.get(v.vendor_id, {}).get("status"),
                                    "quality": ctx.eligibility[v.vendor_id].status} for v in vs]
                item["review_queue"] = sum(v.review_required_lines for v in vs)
                item["avg_coverage"] = round(sum(v.coverage_pct for v in vs) / len(vs), 1) if vs else None
                item["quotations_received"] = sum(1 for v in ctx.extraction.values() if v.get("status") not in (None, "NOT_SUBMITTED"))
                item["scenarios"] = [{"id": s.scenario_id, "name": s.name, "net": s.net_total} for s in ctx.scenarios.values()]
            except Exception as e:  # dashboard must not die because one RFx is mid-processing
                item["error"] = e.__class__.__name__
        out["rfx"].append(item)
    out["kpis"]["active_rfx"] = sum(1 for r in rfxs if r.status in ("PUBLISHED", "EVALUATION"))
    out["kpis"]["vendors"] = db.scalar(select(func.count()).select_from(Vendor).where(Vendor.org_id == user.org_id))
    return out


# ------------------------------------------------------------------ RFx
@router.get("/rfx")
def list_rfx(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{**rfx_dict(r), "line_count": len(r.lines)}
            for r in db.scalars(select(Rfx).where(Rfx.org_id == user.org_id).order_by(Rfx.created_at.desc()))]


@router.get("/rfx/{rfx_id}")
def get_rfx(rfx_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = rfx_for(rfx_id, user, db)
    vids = [rv.vendor_id for rv in db.scalars(select(RfxVendor).where(RfxVendor.rfx_id == r.id))]
    return {**rfx_dict(r), "lines": [line_dict(l) for l in r.lines],
            "questionnaire": [{"qid": q.qid, "text": q.text, "type": q.type, "mandatory": q.mandatory, "pass_rule": q.pass_rule}
                              for q in r.questions],
            "vendors": [vendor_dict(db.get(Vendor, v)) for v in sorted(vids)], "copilot_transcript": r.copilot_transcript}


def _apply_draft(r: Rfx, d: RfxDraft):
    r.title, r.category, r.description = d.title, d.category, d.description
    r.business_justification, r.delivery_location, r.currency = d.business_justification, d.delivery_location, d.currency
    r.required_delivery_days = d.required_delivery_days
    r.submission_deadline = date.fromisoformat(d.submission_deadline) if d.submission_deadline else None
    r.terms = ([RfxTerm(kind="PAYMENT", text=d.payment_terms)] if d.payment_terms else []) + \
              ([RfxTerm(kind="COMMERCIAL", text=d.commercial_terms)] if d.commercial_terms else []) + \
              [RfxTerm(kind="ELIGIBILITY_RULE", text=t) for t in d.vendor_eligibility_rules]
    r.lines = [RfxLineItem(line_id=l.line_id, item_code=l.item_code, name=l.name, description=l.description, spec=l.spec,
                           quantity=l.quantity, uom=l.uom, target_price=l.target_price_inr,
                           required_delivery_days=l.required_delivery_days, mandatory=l.mandatory) for l in d.line_items]
    r.questions = [QuestionnaireQuestion(qid=q.qid, position=i, text=q.text, type=q.type, mandatory=q.mandatory,
                                         pass_rule=q.pass_rule) for i, q in enumerate(d.questionnaire)]


class DraftIn(BaseModel):
    draft: RfxDraft
    copilot_transcript: Optional[list] = None


@router.post("/rfx")
def create_rfx(body: DraftIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.scalar(select(func.count()).select_from(Rfx)) + 148
    r = Rfx(org_id=user.org_id, reference=f"RFX-{date.today().year}-{n:04d}", title=body.draft.title, status="DRAFT",
            created_by=user.id, issue_date=date.today(), copilot_transcript=body.copilot_transcript)
    _apply_draft(r, body.draft)
    db.add(r); db.flush()
    audit(db, "RFX_CREATED", "rfx", r.id, user.id, after={"reference": r.reference, "lines": len(r.lines)})
    return {"id": r.id, "reference": r.reference, "issues": check_draft(body.draft, None)}


@router.put("/rfx/{rfx_id}")
def update_rfx(rfx_id: str, body: DraftIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = rfx_for(rfx_id, user, db)
    if r.status != "DRAFT":
        raise HTTPException(409, "Only draft RFx can be edited; published RFx are immutable for auditability")
    before = {"lines": len(r.lines), "title": r.title}
    _apply_draft(r, body.draft)
    if body.copilot_transcript is not None:
        r.copilot_transcript = body.copilot_transcript
    audit(db, "RFX_UPDATED", "rfx", r.id, user.id, before=before, after={"lines": len(body.draft.line_items), "title": r.title})
    return {"id": r.id, "issues": check_draft(body.draft, None)}


class PublishIn(BaseModel):
    vendor_ids: list[str]


@router.post("/rfx/{rfx_id}/publish")
def publish_rfx(rfx_id: str, body: PublishIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = rfx_for(rfx_id, user, db)
    if not r.lines:
        raise HTTPException(422, "Cannot publish an RFx with no line items")
    for vid in body.vendor_ids:
        if not db.get(Vendor, vid):
            raise HTTPException(422, f"Unknown vendor {vid}")
        db.add(RfxVendor(rfx_id=r.id, vendor_id=vid, channel="EMAIL_STUB"))
        db.add(Submission(rfx_id=r.id, vendor_id=vid, status="AWAITING"))
    r.status = "PUBLISHED"
    audit(db, "RFX_PUBLISHED", "rfx", r.id, user.id, meta={"vendors": body.vendor_ids, "channel": "EMAIL_STUB (no email sent)"})
    return {"ok": True, "note": "Invitations recorded. Email sending is stubbed in this build."}


class CopilotIn(BaseModel):
    history: list[dict[str, Any]] = []
    text: str
    draft: Optional[RfxDraft] = None


@router.post("/rfx/copilot")
def copilot(body: CopilotIn, user: User = Depends(current_user)):
    llm = get_llm()
    if llm is None:
        raise HTTPException(503, "AI co-pilot unavailable: no AI key configured (GEMINI_API_KEY or ANTHROPIC_API_KEY). You can still create an RFx manually.")
    try:
        t = copilot_turn(llm, body.history, body.text, body.draft)
    except LLMError as e:
        raise HTTPException(502, str(e))
    return t.model_dump()


# ------------------------------------------------------------------ vendors
@router.get("/vendors")
def vendors(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [vendor_dict(v) for v in db.scalars(select(Vendor).where(Vendor.org_id == user.org_id).order_by(Vendor.id))]


@router.get("/vendors/{vendor_id}")
def vendor(vendor_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = db.get(Vendor, vendor_id)
    if not v or v.org_id != user.org_id:
        raise HTTPException(404, "Vendor not found")
    return vendor_dict(v)


# ------------------------------------------------------------------ submissions & documents
def _job_dict(j: Optional[ExtractionJob]):
    if not j:
        return None
    return {"id": j.id, "status": j.status, "attempts": j.attempts, "model": j.model, "error": j.error,
            "started_at": j.started_at, "finished_at": j.finished_at}


def _doc_dict(d: Document):
    return {"id": d.id, "filename": d.filename, "kind": d.kind, "format": d.doc_format, "version": d.version,
            "sha256": d.sha256[:12], "size_bytes": d.size_bytes, "uploaded_at": d.uploaded_at, "superseded": bool(d.superseded_by),
            "job": _job_dict(d.jobs[-1] if d.jobs else None)}


@router.get("/rfx/{rfx_id}/submissions")
def submissions(rfx_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = rfx_for(rfx_id, user, db)
    out = []
    for s in db.scalars(select(Submission).where(Submission.rfx_id == r.id).order_by(Submission.vendor_id)):
        v = db.get(Vendor, s.vendor_id)
        out.append({"id": s.id, "vendor": vendor_dict(v), "status": s.status, "received_at": s.received_at,
                    "documents": [_doc_dict(d) for d in s.documents]})
    return out


@router.post("/rfx/{rfx_id}/vendors/{vendor_id}/documents")
async def upload(rfx_id: str, vendor_id: str, background: BackgroundTasks, file: UploadFile = File(...),
                 kind: str = Form("QUOTATION"), user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = rfx_for(rfx_id, user, db)
    if kind not in ("QUOTATION", "CERTIFICATE", "OTHER"):
        raise HTTPException(422, "kind must be QUOTATION, CERTIFICATE or OTHER")
    if not db.scalar(select(RfxVendor).where(RfxVendor.rfx_id == r.id, RfxVendor.vendor_id == vendor_id)):
        raise HTTPException(422, "Vendor was not invited to this RFx")
    limit = int(get_settings().max_upload_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds {get_settings().max_upload_mb:.0f} MB")
    suffix = Path(file.filename or "upload").suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        doc = register_document(db, r, vendor_id, tmp_path, file.filename or f"upload{suffix}", kind, user.id)
    except UnsupportedDocument as e:
        raise HTTPException(422, str(e))
    finally:
        tmp_path.unlink(missing_ok=True)
    job = None
    if kind in ("QUOTATION", "CERTIFICATE"):
        job = queue_extraction(db, doc, user.id)
        db.commit()
        if job.status == "QUEUED":
            background.add_task(run_job, job.id)
    return {"document": _doc_dict(doc), "job": _job_dict(job)}


@router.get("/documents/{doc_id}")
def document(doc_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    rfx_for(d.rfx_id, user, db)
    segs = [{"id": s.segment_id, "text": s.text, "locator": s.locator, "ocr_confidence": s.ocr_confidence}
            for s in db.scalars(select(SourceEvidence).where(SourceEvidence.document_id == d.id))]
    segs.sort(key=lambda s: s["id"])
    res = db.scalar(select(ExtractionResult).where(ExtractionResult.document_id == d.id).order_by(ExtractionResult.created_at.desc()))
    outcome = res.outcome if res else None
    if outcome and d.kind == "QUOTATION":
        outcome = {k: outcome.get(k) for k in ("status", "header_fields", "lines", "coverage", "exceptions", "error", "model",
                                               "attempts", "quotation")}
        if outcome.get("quotation"):
            outcome["discounts"] = outcome["quotation"].get("discounts")
            outcome["unresolved_references"] = outcome["quotation"].get("unresolved_references")
            outcome["document_warnings"] = outcome["quotation"].get("document_warnings")
            outcome.pop("quotation")
    reviews = [{"line_id": f.rfx_line_id, "action": f.action, "after": f.after, "comment": f.comment, "at": f.created_at}
               for f in db.scalars(select(FieldReview).where(FieldReview.rfx_id == d.rfx_id, FieldReview.vendor_id == d.vendor_id)
                                   .order_by(FieldReview.created_at))]
    v = db.get(Vendor, d.vendor_id)
    return {**_doc_dict(d), "rfx_id": d.rfx_id, "vendor": vendor_dict(v), "segments": segs, "extraction": outcome,
            "reviews": reviews, "has_derived_image": bool(d.derived_path)}


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: str, derived: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    rfx_for(d.rfx_id, user, db)
    p = Path(d.derived_path if derived and d.derived_path else d.stored_path)
    if not p.exists():
        raise HTTPException(404, "File missing from storage")
    return FileResponse(p, filename=d.filename if not derived else f"{Path(d.filename).stem}.corrected.png",
                        content_disposition_type="inline")


class ExtractIn(BaseModel):
    force: bool = False


@router.post("/documents/{doc_id}/extract")
def extract(doc_id: str, body: ExtractIn, background: BackgroundTasks, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    rfx_for(d.rfx_id, user, db)
    job = queue_extraction(db, d, user.id, force=body.force)
    db.commit()
    if job.status == "QUEUED":
        background.add_task(run_job, job.id)
    return _job_dict(job)


@router.post("/extraction/{job_id}/retry")
def retry(job_id: str, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    j = db.get(ExtractionJob, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    d = db.get(Document, j.document_id)
    rfx_for(d.rfx_id, user, db)
    job = queue_extraction(db, d, user.id, force=True)
    db.commit()
    background.add_task(run_job, job.id)
    return _job_dict(job)
