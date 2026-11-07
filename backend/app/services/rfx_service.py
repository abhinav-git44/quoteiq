"""DB <-> core adapters, extraction jobs, analysis context, scenario persistence, exports."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.llm import get_llm
from app.analyst.builder import build_context
from app.analyst.context import AnalysisContext
from app.core.config import get_settings
from app.db.models import (AwardAllocation, AwardScenario, Document, ExchangeRate, ExtractedLineItem, ExtractionJob,
                           ExtractionResult, FieldReview, NormalizedQuotation, QuestionnaireQuestion, ReportExport,
                           Rfx, RfxVendor, SourceEvidence, Submission, Vendor, VendorQuestionnaireAnswer)
from app.db.session import session_scope
from app.domain.extraction import ExtractionOutcome
from app.extraction.parsers import detect_format, sha256_file
from app.extraction.pipeline import extract_certificate, extract_quotation
from app.optimization.award import Scenario
from app.reporting import exports as X
from app.services.common import audit, store_file

log = logging.getLogger("quoteiq.service")
PROMPT_VERSION = "v1"
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="extract")


# ------------------------------------------------------------------ conversions
def line_dict(l) -> dict:
    return {"line_id": l.line_id, "item_code": l.item_code, "name": l.name, "description": l.description, "spec": l.spec or {},
            "quantity": l.quantity, "uom": l.uom, "target_price_inr": l.target_price,
            "required_delivery_days": l.required_delivery_days, "mandatory": l.mandatory}


def rfx_dict(r: Rfx) -> dict:
    return {"id": r.id, "reference": r.reference, "title": r.title, "category": r.category, "description": r.description,
            "business_justification": r.business_justification, "delivery_location": r.delivery_location,
            "issue_date": r.issue_date.isoformat() if r.issue_date else None,
            "submission_deadline": r.submission_deadline.isoformat() if r.submission_deadline else None,
            "currency": r.currency, "required_delivery_days": r.required_delivery_days, "status": r.status,
            "terms": [{"kind": t.kind, "text": t.text} for t in r.terms]}


def vendor_dict(v: Vendor) -> dict:
    c = v.contacts[0] if v.contacts else None
    return {"vendor_id": v.id, "name": v.name, "city": v.city, "address": v.address, "categories": v.categories,
            "certifications": v.certifications, "capacity_tpm": v.capacity_tpm, "historical_score": v.historical_score,
            "submission_format": v.submission_format, "contact": c.name if c else None, "email": c.email if c else None}


def question_dict(q: QuestionnaireQuestion) -> dict:
    return {"qid": q.qid, "text": q.text, "type": q.type, "mandatory": q.mandatory, "pass_rule": q.pass_rule or {}}


# ------------------------------------------------------------------ documents & extraction
def register_document(db: Session, rfx: Rfx, vendor_id: str, src: Path, filename: str, kind: str = "QUOTATION",
                      user_id: Optional[str] = None) -> Document:
    s = get_settings()
    fmt = detect_format(src, s.max_upload_mb)          # raises UnsupportedDocument with a user-facing message
    sha = sha256_file(src)
    sub = db.scalar(select(Submission).where(Submission.rfx_id == rfx.id, Submission.vendor_id == vendor_id))
    if sub is None:
        sub = Submission(rfx_id=rfx.id, vendor_id=vendor_id, status="AWAITING")
        db.add(sub); db.flush()
    existing = db.scalar(select(Document).where(Document.rfx_id == rfx.id, Document.vendor_id == vendor_id,
                                                Document.kind == kind, Document.sha256 == sha, Document.superseded_by.is_(None)))
    if existing:
        return existing                                  # idempotent re-upload
    prev = db.scalars(select(Document).where(Document.rfx_id == rfx.id, Document.vendor_id == vendor_id,
                                             Document.kind == kind, Document.superseded_by.is_(None))).all()
    stored = store_file(src, rfx.id, vendor_id, filename)
    doc = Document(rfx_id=rfx.id, submission_id=sub.id, vendor_id=vendor_id, kind=kind, filename=filename,
                   stored_path=str(stored), sha256=sha, size_bytes=stored.stat().st_size, doc_format=fmt,
                   version=len(prev) + 1, uploaded_by=user_id)
    db.add(doc); db.flush()
    for p in prev:
        p.superseded_by = doc.id
    if kind == "QUOTATION":
        sub.status, sub.received_at, sub.channel = "RECEIVED", datetime.now(timezone.utc), "UPLOAD"
    audit(db, "DOCUMENT_UPLOADED", "document", doc.id, user_id, after={"filename": filename, "sha256": sha, "kind": kind,
                                                                       "version": doc.version}, document_id=doc.id)
    return doc


def queue_extraction(db: Session, doc: Document, user_id: Optional[str] = None, force: bool = False) -> ExtractionJob:
    s = get_settings()
    key = f"{doc.sha256}:{doc.kind}:{s.active_model or 'no-ai'}:{PROMPT_VERSION}"
    if force:
        key += f":retry-{datetime.now(timezone.utc).timestamp()}"
    job = db.scalar(select(ExtractionJob).where(ExtractionJob.idempotency_key == key))
    if job and job.status in ("QUEUED", "RUNNING", "SUCCEEDED", "NEEDS_REVIEW"):
        return job
    if job is None:
        job = ExtractionJob(document_id=doc.id, idempotency_key=key, prompt_version=PROMPT_VERSION,
                            model=s.active_model)
        db.add(job)
    job.status = "QUEUED"
    db.flush()
    audit(db, "EXTRACTION_QUEUED", "extraction_job", job.id, user_id, document_id=doc.id, meta={"force": force})
    return job


def submit_job(job_id: str):
    _pool.submit(run_job, job_id)


def run_job(job_id: str) -> None:
    """Runs in a worker thread with its own session. Never raises."""
    try:
        with session_scope() as db:
            job = db.get(ExtractionJob, job_id)
            doc = db.get(Document, job.document_id)
            rfx = db.get(Rfx, doc.rfx_id)
            vendor = db.get(Vendor, doc.vendor_id)
            job.status, job.started_at, job.attempts = "RUNNING", datetime.now(timezone.utc), job.attempts + 1
            sub = db.get(Submission, doc.submission_id)
            if doc.kind == "QUOTATION":
                sub.status = "PROCESSING"
            db.flush()
            lines = [line_dict(l) for l in rfx.lines]
            llm = get_llm()
            derived = get_settings().storage_path / "derived" / doc.id
            if doc.kind == "CERTIFICATE":
                r = extract_certificate(doc.stored_path, llm)
                c = r.get("certificate")
                payload = {"status": r["status"], "valid_until": c.valid_until.value if c else None,
                           "number": c.certificate_number.value if c else None,
                           "holder": c.holder_name.value if c else None,
                           "confidence": r.get("valid_until_confidence"),
                           "segment_id": c.valid_until.segment_id if c else None,
                           "snippet": c.valid_until.snippet if c else None, "document_id": doc.id}
                status = r["status"]
                job.error = r.get("error")
                _store_segments(db, doc, r["document"].segments)
                db.add(ExtractionResult(job_id=job.id, document_id=doc.id, status=status, outcome=payload))
            else:
                oc = extract_quotation(doc.stored_path, lines, llm, derived_dir=derived, vendor_hint=vendor.name)
                status = oc.status
                if oc.document:
                    _store_segments(db, doc, oc.document.segments)
                    doc.derived_path = oc.document.derived_image_path
                res = ExtractionResult(job_id=job.id, document_id=doc.id, status=status, outcome=oc.model_dump(mode="json"))
                db.add(res); db.flush()
                for v in oc.lines:
                    l = v.llm
                    db.add(ExtractedLineItem(result_id=res.id, vendor_id=doc.vendor_id, rfx_line_id=l.rfx_line_id,
                                             vendor_description=l.vendor_description, price=l.price,
                                             currency=l.price_currency, price_uom=l.price_uom.value,
                                             units_per_price_uom=l.units_per_price_uom, line_discount_pct=l.line_discount_pct,
                                             confidence=v.confidence, review_required=v.review_required,
                                             flags=[f.value for f in l.flags], segment_id=l.segment_id, snippet=l.snippet,
                                             checks=[c.model_dump() for c in v.checks]))
                sub.status = {"SUCCEEDED": "READY", "NEEDS_REVIEW": "NEEDS_REVIEW"}.get(status, "FAILED")
                job.error = oc.error
            job.status, job.finished_at = status, datetime.now(timezone.utc)
            job.model = getattr(llm, "model", None)
            audit(db, "EXTRACTION_COMPLETED", "extraction_job", job.id, None, document_id=doc.id,
                  after={"status": status, "error": job.error})
            db.flush()
            snapshot_normalized(db, rfx.id)
    except Exception as e:  # pragma: no cover - defensive
        log.exception("Extraction job %s crashed", job_id)
        with session_scope() as db:
            job = db.get(ExtractionJob, job_id)
            if job:
                job.status, job.error, job.finished_at = "FAILED", f"Internal error: {e.__class__.__name__}", datetime.now(timezone.utc)


def _store_segments(db: Session, doc: Document, segments) -> None:
    db.execute(delete(SourceEvidence).where(SourceEvidence.document_id == doc.id))
    for sgm in segments:
        db.add(SourceEvidence(document_id=doc.id, segment_id=sgm.id, locator=sgm.locator, text=sgm.text,
                              ocr_confidence=sgm.ocr_confidence))


# ------------------------------------------------------------------ analysis context
def _latest_result(db: Session, rfx_id: str, vendor_id: str, kind: str) -> tuple[Optional[Document], Optional[ExtractionResult]]:
    doc = db.scalar(select(Document).where(Document.rfx_id == rfx_id, Document.vendor_id == vendor_id, Document.kind == kind,
                                           Document.superseded_by.is_(None)).order_by(Document.uploaded_at.desc()))
    if not doc:
        return None, None
    res = db.scalar(select(ExtractionResult).where(ExtractionResult.document_id == doc.id)
                    .order_by(ExtractionResult.created_at.desc()))
    return doc, res


def corrections_for(db: Session, rfx_id: str) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for fr in db.scalars(select(FieldReview).where(FieldReview.rfx_id == rfx_id).order_by(FieldReview.created_at)):
        c = out.setdefault(fr.vendor_id, {}).setdefault(fr.rfx_line_id, {})
        if fr.action == "CONFIRM":
            c["reviewed"] = True
        elif fr.action == "CORRECT":
            c.update({k: v for k, v in (fr.after or {}).items()
                      if k in ("price", "price_uom", "units_per_price_uom", "currency", "line_discount_pct")})
            c["reviewed"] = True
            c.setdefault("status", "QUOTED")
        elif fr.action == "ACCEPT_ASSUMPTION":
            c.setdefault("accepted_assumptions", []).append((fr.after or {}).get("assumption", "DERIVED_WEIGHT"))
            c["reviewed"] = True
        elif fr.action == "MARK_NOT_QUOTED":
            c["status"] = "NOT_QUOTED"
        elif fr.action == "MARK_NEEDS_CLARIFICATION":
            c["status"] = "NEEDS_CLARIFICATION"
    return out


def build_rfx_context(db: Session, rfx_id: str, user_id: Optional[str] = None) -> AnalysisContext:
    rfx = db.get(Rfx, rfx_id)
    if rfx is None:
        raise KeyError(rfx_id)
    vids = [rv.vendor_id for rv in db.scalars(select(RfxVendor).where(RfxVendor.rfx_id == rfx_id))]
    vendors = [vendor_dict(db.get(Vendor, v)) for v in sorted(vids)]
    questions = [question_dict(q) for q in rfx.questions]
    answers, overrides = {}, {}
    for a in db.scalars(select(VendorQuestionnaireAnswer).where(VendorQuestionnaireAnswer.rfx_id == rfx_id)):
        answers.setdefault(a.vendor_id, {})[a.qid] = a.answer
        if a.reviewer_status:
            overrides.setdefault(a.vendor_id, {})[a.qid] = {"status": a.reviewer_status, "comment": a.reviewer_comment}
    outcomes, certs, doc_ids = {}, {}, {}
    for vid in vids:
        doc, res = _latest_result(db, rfx_id, vid, "QUOTATION")
        if res is not None:
            outcomes[vid] = ExtractionOutcome.model_validate(res.outcome)
            doc_ids[vid] = doc.id
        cdoc, cres = _latest_result(db, rfx_id, vid, "CERTIFICATE")
        if cres is not None:
            certs[vid] = cres.outcome
    fx = [{"from_currency": r.from_currency, "to_currency": r.to_currency, "rate": r.rate, "rate_date": r.rate_date,
           "source": r.source, "rate_type": r.rate_type} for r in db.scalars(select(ExchangeRate))]

    def on_scenario(s: Scenario):
        persist_scenario(db, rfx_id, s, user_id)

    def exporter(kind: str, params: dict) -> dict:
        return create_export(db, ctx, rfx_id, kind, params.get("scenario_id"), user_id)

    rd = rfx_dict(rfx)
    ctx = build_context(rfx=rd, lines=[line_dict(l) for l in rfx.lines], vendors=vendors, questionnaire=questions,
                        answers=answers, cert_evidence=certs, outcomes=outcomes, fx_rates=fx,
                        corrections=corrections_for(db, rfx_id), qa_overrides=overrides, document_ids=doc_ids,
                        exporter=exporter, on_scenario=on_scenario)
    for sc in db.scalars(select(AwardScenario).where(AwardScenario.rfx_id == rfx_id)):
        try:
            ctx.scenarios[sc.scenario_id] = Scenario.model_validate(sc.data)
        except Exception:
            pass
    return ctx


def snapshot_normalized(db: Session, rfx_id: str) -> None:
    ctx = build_rfx_context(db, rfx_id)
    db.execute(delete(NormalizedQuotation).where(NormalizedQuotation.rfx_id == rfx_id))
    for q in ctx.norm.quotes:
        db.add(NormalizedQuotation(rfx_id=rfx_id, vendor_id=q.vendor_id, rfx_line_id=q.rfx_line_id, status=q.status,
                                   unit_price_base=q.unit_price_base, landed_unit_price=q.landed_unit_price,
                                   line_value_base=q.line_value_base, confidence=q.confidence,
                                   review_required=q.review_required, detail=q.model_dump(mode="json")))
    audit(db, "NORMALIZATION_RECOMPUTED", "rfx", rfx_id, meta={"quotes": len(ctx.norm.quotes), "policy": ctx.norm.policy})


def persist_scenario(db: Session, rfx_id: str, s: Scenario, user_id: Optional[str]) -> AwardScenario:
    row = db.scalar(select(AwardScenario).where(AwardScenario.rfx_id == rfx_id, AwardScenario.scenario_id == s.scenario_id))
    data = s.model_dump(mode="json")
    if row is None:
        row = AwardScenario(rfx_id=rfx_id, scenario_id=s.scenario_id, created_by=user_id)
        db.add(row)
    elif row.status == "APPROVED":
        return row       # approved scenarios are immutable
    row.name, row.strategy, row.params, row.data = s.name, s.strategy, s.params.model_dump(mode="json"), data
    row.gross_total, row.net_total = s.gross_total, s.net_total
    row.lines_allocated, row.lines_unallocated = s.lines_allocated, s.lines_unallocated
    db.flush()
    db.execute(delete(AwardAllocation).where(AwardAllocation.scenario_pk == row.id))
    for a in s.allocations:
        db.add(AwardAllocation(scenario_pk=row.id, rfx_line_id=a.line_id, vendor_id=a.vendor_id, unit_price=a.unit_price,
                               quantity=a.quantity, value=a.value, review_required=a.review_required))
    for u in s.unallocated:
        db.add(AwardAllocation(scenario_pk=row.id, rfx_line_id=u["line_id"], vendor_id=None, quantity=u["quantity"],
                               note=u["reason"]))
    audit(db, "AWARD_SCENARIO_GENERATED", "award_scenario", s.scenario_id, user_id,
          after={"name": s.name, "net_total": s.net_total, "params": s.params.model_dump(mode="json")})
    return row


def create_export(db: Session, ctx: AnalysisContext, rfx_id: str, kind: str, scenario_id: Optional[str],
                  user_id: Optional[str]) -> dict:
    from app.db.models import AuditLog
    d = get_settings().storage_path / "reports" / rfx_id
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ref = ctx.rfx["reference"]
    if kind == "comparison_xlsx":
        p = X.comparison_xlsx(ctx, d / f"{ref}_comparison_{stamp}.xlsx")
    elif kind == "exceptions_xlsx":
        p = X.exceptions_xlsx(ctx, d / f"{ref}_exceptions_{stamp}.xlsx")
    elif kind == "quality_pdf":
        p = X.quality_pdf(ctx, d / f"{ref}_quality_{stamp}.pdf")
    elif kind == "award_pdf":
        s = ctx.scenarios[scenario_id]
        row = db.scalar(select(AwardScenario).where(AwardScenario.rfx_id == rfx_id, AwardScenario.scenario_id == scenario_id))
        approval = ({"approved_by": row.approved_by, "approved_at": row.approved_at.isoformat()}
                    if row is not None and row.status == "APPROVED" else None)
        baseline = None
        if s.strategy != "SINGLE_VENDOR":
            from app.optimization.award import build_scenario
            meta = {v["vendor_id"]: v for v in ctx.vendors}
            baseline = build_scenario(ctx.norm, ctx.eligibility, ctx.lines, meta,
                                      s.params.model_copy(update={"strategy": "SINGLE_VENDOR", "max_vendors": None,
                                                                  "max_share_pct": None, "name": None}))
        p = X.award_pdf(ctx, s, d / f"{ref}_award_{scenario_id}_{stamp}.pdf", baseline=baseline, approval=approval)
    elif kind == "audit_csv":
        rows = [{"event_id": a.id, "timestamp": a.created_at.isoformat(), "user": a.user_id, "action": a.action,
                 "entity_type": a.entity_type, "entity_id": a.entity_id, "document_id": a.document_id,
                 "before": a.before, "after": a.after, "metadata": a.meta}
                for a in db.scalars(select(AuditLog).order_by(AuditLog.created_at))]
        p = X.audit_csv(rows, d / f"{ref}_audit_{stamp}.csv")
    else:
        raise ValueError(f"Unknown export kind {kind}")
    rep = ReportExport(rfx_id=rfx_id, kind=kind, scenario_id=scenario_id, filename=p.name, stored_path=str(p), created_by=user_id)
    db.add(rep); db.flush()
    audit(db, "REPORT_EXPORTED", "report", rep.id, user_id, meta={"kind": kind, "scenario_id": scenario_id})
    return {"report_id": rep.id, "filename": p.name, "download_url": f"/api/reports/{rep.id}/download"}
