"""PostgreSQL schema (SQLAlchemy 2.0). Core business entities are relational; JSONB is used
only for genuinely flexible payloads (specs, extraction metadata, calculation traces)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class Organization(Base, Timestamped):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class User(Base, Timestamped):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="BUYER", nullable=False)   # BUYER / APPROVER / ADMIN
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)


class Vendor(Base, Timestamped):
    __tablename__ = "vendors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)          # e.g. "V-A"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[Optional[str]] = mapped_column(String(120))
    address: Mapped[Optional[str]] = mapped_column(Text)
    categories: Mapped[list] = mapped_column(JSONType, default=list)
    certifications: Mapped[list] = mapped_column(JSONType, default=list)
    capacity_tpm: Mapped[Optional[float]] = mapped_column(Float)
    historical_score: Mapped[Optional[float]] = mapped_column(Float)
    submission_format: Mapped[Optional[str]] = mapped_column(String(20))
    contacts: Mapped[list["VendorContact"]] = relationship(back_populates="vendor", cascade="all, delete-orphan")


class VendorContact(Base, Timestamped):
    __tablename__ = "vendor_contacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    vendor: Mapped[Vendor] = relationship(back_populates="contacts")


class Rfx(Base, Timestamped):
    __tablename__ = "rfx"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text)
    business_justification: Mapped[Optional[str]] = mapped_column(Text)
    delivery_location: Mapped[Optional[str]] = mapped_column(Text)
    issue_date: Mapped[Optional[date]] = mapped_column(Date)
    submission_deadline: Mapped[Optional[date]] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    required_delivery_days: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)   # DRAFT/PUBLISHED/EVALUATION/AWARDED
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    copilot_transcript: Mapped[Optional[list]] = mapped_column(JSONType)
    lines: Mapped[list["RfxLineItem"]] = relationship(back_populates="rfx", cascade="all, delete-orphan", order_by="RfxLineItem.line_id")
    terms: Mapped[list["RfxTerm"]] = relationship(cascade="all, delete-orphan")
    questions: Mapped[list["QuestionnaireQuestion"]] = relationship(cascade="all, delete-orphan", order_by="QuestionnaireQuestion.position")


class RfxTerm(Base):
    __tablename__ = "rfx_terms"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40))          # PAYMENT / COMMERCIAL / ELIGIBILITY_RULE
    text: Mapped[str] = mapped_column(Text)


class RfxLineItem(Base, Timestamped):
    __tablename__ = "rfx_line_items"
    __table_args__ = (UniqueConstraint("rfx_id", "line_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), nullable=False, index=True)
    line_id: Mapped[str] = mapped_column(String(10), nullable=False)
    item_code: Mapped[Optional[str]] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    spec: Mapped[dict] = mapped_column(JSONType, default=dict)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    uom: Mapped[str] = mapped_column(String(10), nullable=False)
    target_price: Mapped[Optional[float]] = mapped_column(Float)
    required_delivery_days: Mapped[Optional[int]] = mapped_column(Integer)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    rfx: Mapped[Rfx] = relationship(back_populates="lines")


class RfxVendor(Base, Timestamped):
    __tablename__ = "rfx_vendors"
    __table_args__ = (UniqueConstraint("rfx_id", "vendor_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), index=True)
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    channel: Mapped[str] = mapped_column(String(20), default="EMAIL_STUB")


class QuestionnaireQuestion(Base):
    __tablename__ = "questionnaire_questions"
    __table_args__ = (UniqueConstraint("rfx_id", "qid"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), index=True)
    qid: Mapped[str] = mapped_column(String(10))
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(20))
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    pass_rule: Mapped[dict] = mapped_column(JSONType, default=dict)


class VendorQuestionnaireAnswer(Base, Timestamped):
    __tablename__ = "vendor_questionnaire_answers"
    __table_args__ = (UniqueConstraint("rfx_id", "vendor_id", "qid"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), index=True)
    qid: Mapped[str] = mapped_column(String(10))
    answer: Mapped[Any] = mapped_column(JSONType)
    evidence_document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("documents.id"))
    reviewer_status: Mapped[Optional[str]] = mapped_column(String(20))   # PASS/FAIL/... override
    reviewer_comment: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Submission(Base, Timestamped):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("rfx_id", "vendor_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="AWAITING")   # AWAITING/RECEIVED/PROCESSING/NEEDS_REVIEW/READY/FAILED
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    channel: Mapped[Optional[str]] = mapped_column(String(20))
    documents: Mapped[list["Document"]] = relationship(back_populates="submission", order_by="Document.uploaded_at")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_rfx_sha", "rfx_id", "sha256"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), index=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="QUOTATION")      # QUOTATION / CERTIFICATE / OTHER
    filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(Text)
    derived_path: Mapped[Optional[str]] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    doc_format: Mapped[Optional[str]] = mapped_column(String(10))
    version: Mapped[int] = mapped_column(Integer, default=1)
    superseded_by: Mapped[Optional[str]] = mapped_column(String(36))
    uploaded_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    submission: Mapped[Submission] = relationship(back_populates="documents")
    jobs: Mapped[list["ExtractionJob"]] = relationship(back_populates="document", order_by="ExtractionJob.created_at")


class ExtractionJob(Base, Timestamped):
    __tablename__ = "extraction_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)  # QUEUED/RUNNING/SUCCEEDED/NEEDS_REVIEW/FAILED/AI_UNAVAILABLE
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[Optional[str]] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    idempotency_key: Mapped[str] = mapped_column(String(160))
    error: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    document: Mapped[Document] = relationship(back_populates="jobs")


class ExtractionResult(Base):
    __tablename__ = "extraction_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("extraction_jobs.id", ondelete="CASCADE"), unique=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[dict] = mapped_column(JSONType)          # full validated ExtractionOutcome (incl. raw model output)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExtractedLineItem(Base):
    __tablename__ = "extracted_line_items"
    __table_args__ = (Index("ix_eli_result_line", "result_id", "rfx_line_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    result_id: Mapped[str] = mapped_column(ForeignKey("extraction_results.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    rfx_line_id: Mapped[Optional[str]] = mapped_column(String(10))
    vendor_description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[Optional[float]] = mapped_column(Float)
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    price_uom: Mapped[Optional[str]] = mapped_column(String(20))
    units_per_price_uom: Mapped[Optional[float]] = mapped_column(Float)
    line_discount_pct: Mapped[Optional[float]] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    review_required: Mapped[bool] = mapped_column(Boolean)
    flags: Mapped[list] = mapped_column(JSONType, default=list)
    segment_id: Mapped[Optional[str]] = mapped_column(String(10))
    snippet: Mapped[Optional[str]] = mapped_column(Text)
    checks: Mapped[list] = mapped_column(JSONType, default=list)


class SourceEvidence(Base):
    __tablename__ = "source_evidence"
    __table_args__ = (UniqueConstraint("document_id", "segment_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    segment_id: Mapped[str] = mapped_column(String(10))
    locator: Mapped[dict] = mapped_column(JSONType)
    text: Mapped[str] = mapped_column(Text)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float)


class FieldReview(Base):
    """Human corrections / confirmations. Never overwrites extraction; layered on top."""
    __tablename__ = "field_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), index=True)
    rfx_line_id: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(30))   # CONFIRM / CORRECT / ACCEPT_ASSUMPTION / MARK_NOT_QUOTED / MARK_NEEDS_CLARIFICATION
    before: Mapped[Optional[dict]] = mapped_column(JSONType)
    after: Mapped[Optional[dict]] = mapped_column(JSONType)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (UniqueConstraint("from_currency", "to_currency", "rate_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    from_currency: Mapped[str] = mapped_column(String(3))
    to_currency: Mapped[str] = mapped_column(String(3))
    rate: Mapped[float] = mapped_column(Float)
    rate_date: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(120))
    rate_type: Mapped[str] = mapped_column(String(20))   # ASSUMED_DEMO / MANUAL / MARKET


class UnitConversion(Base):
    __tablename__ = "unit_conversions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    from_uom: Mapped[str] = mapped_column(String(20))
    to_uom: Mapped[str] = mapped_column(String(20))
    factor: Mapped[Optional[float]] = mapped_column(Float)
    rule: Mapped[str] = mapped_column(Text)


class NormalizedQuotation(Base):
    __tablename__ = "normalized_quotations"
    __table_args__ = (UniqueConstraint("rfx_id", "vendor_id", "rfx_line_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    rfx_line_id: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(25))
    unit_price_base: Mapped[Optional[float]] = mapped_column(Float)
    landed_unit_price: Mapped[Optional[float]] = mapped_column(Float)
    line_value_base: Mapped[Optional[float]] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    review_required: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[dict] = mapped_column(JSONType)      # trace, assumptions, evidence
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AwardScenario(Base):
    __tablename__ = "award_scenarios"
    __table_args__ = (UniqueConstraint("rfx_id", "scenario_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    strategy: Mapped[str] = mapped_column(String(30))
    params: Mapped[dict] = mapped_column(JSONType)
    gross_total: Mapped[float] = mapped_column(Float)
    net_total: Mapped[float] = mapped_column(Float)
    lines_allocated: Mapped[int] = mapped_column(Integer)
    lines_unallocated: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONType)          # full Scenario
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")   # DRAFT / PREFERRED / APPROVED / SUPERSEDED
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    approved_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approval_comment: Mapped[Optional[str]] = mapped_column(Text)
    allocations: Mapped[list["AwardAllocation"]] = relationship(cascade="all, delete-orphan")


class AwardAllocation(Base):
    __tablename__ = "award_allocations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    scenario_pk: Mapped[str] = mapped_column(ForeignKey("award_scenarios.id", ondelete="CASCADE"), index=True)
    rfx_line_id: Mapped[str] = mapped_column(String(10))
    vendor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vendors.id"))     # null = UNALLOCATED
    unit_price: Mapped[Optional[float]] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    value: Mapped[Optional[float]] = mapped_column(Float)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[Optional[str]] = mapped_column(Text)


class AnalystConversation(Base, Timestamped):
    __tablename__ = "analyst_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    title: Mapped[Optional[str]] = mapped_column(String(300))
    transcript: Mapped[list] = mapped_column(JSONType, default=list)   # API-format messages for continuity
    messages: Mapped[list["AnalystMessage"]] = relationship(cascade="all, delete-orphan", order_by="AnalystMessage.created_at")


class AnalystMessage(Base):
    __tablename__ = "analyst_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("analyst_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list] = mapped_column(JSONType, default=list)
    displays: Mapped[list] = mapped_column(JSONType, default=list)
    ungrounded_numbers: Mapped[list] = mapped_column(JSONType, default=list)
    model: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[Optional[str]] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[Optional[str]] = mapped_column(String(60))
    document_id: Mapped[Optional[str]] = mapped_column(String(36))
    before: Mapped[Optional[dict]] = mapped_column(JSONType)
    after: Mapped[Optional[dict]] = mapped_column(JSONType)
    meta: Mapped[Optional[dict]] = mapped_column("metadata", JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class ReportExport(Base):
    __tablename__ = "report_exports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rfx_id: Mapped[str] = mapped_column(ForeignKey("rfx.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    scenario_id: Mapped[Optional[str]] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(200))
    stored_path: Mapped[str] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
