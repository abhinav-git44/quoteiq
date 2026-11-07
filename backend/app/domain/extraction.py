"""Schemas for document extraction.

Two layers, deliberately separate:
  * `LLM*` models are what the model must return. They are validated with Pydantic
    and are never trusted on their own.
  * `Validated*` models are produced by deterministic checks (grounding, arithmetic,
    spec consistency) and carry the heuristic confidence that the UI shows.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ------------------------------------------------------------------ source documents
class Segment(BaseModel):
    id: str                       # "S012" — stable id the model must cite
    text: str
    locator: dict[str, Any]       # {"kind": "xlsx_row", "sheet": "...", "row": 12} / {"kind":"pdf_line","page":1,"line":7,"bbox":[...]}
    ocr_confidence: Optional[float] = None   # 0-100 for OCR segments


class SourceDocument(BaseModel):
    filename: str
    doc_format: Literal["xlsx", "xls", "pdf", "docx", "image", "email", "text"]
    sha256: str
    segments: list[Segment]
    meta: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    derived_image_path: Optional[str] = None   # perspective-corrected image (photos)

    def segment(self, sid: str | None) -> Optional[Segment]:
        if not sid:
            return None
        for s in self.segments:
            if s.id == sid:
                return s
        return None

    def as_prompt_text(self) -> str:
        out = []
        for s in self.segments:
            loc = s.locator
            where = ", ".join(f"{k}={v}" for k, v in loc.items() if k not in ("kind", "bbox"))
            conf = f" ocr_conf={s.ocr_confidence:.0f}" if s.ocr_confidence is not None else ""
            out.append(f"[{s.id}] ({where}{conf}) {s.text}")
        return "\n".join(out)


# ------------------------------------------------------------------ LLM output
class PriceUOM(str, Enum):
    PIECE = "PIECE"; SET = "SET"; ROLL = "ROLL"; HUNDRED = "HUNDRED"; THOUSAND = "THOUSAND"
    KG = "KG"; BUNDLE = "BUNDLE"; BOX = "BOX"; PACK = "PACK"; CARTON = "CARTON"
    METER = "METER"; SQ_METER = "SQ_METER"; OTHER = "OTHER"


class LineFlag(str, Enum):
    HANDWRITTEN_CORRECTION = "HANDWRITTEN_CORRECTION"
    ILLEGIBLE = "ILLEGIBLE"
    CATEGORY_PRICE = "CATEGORY_PRICE"
    SPEC_DEVIATION = "SPEC_DEVIATION"
    SUBSTITUTE_OFFERED = "SUBSTITUTE_OFFERED"
    OCR_VISION_DISAGREE = "OCR_VISION_DISAGREE"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"


class Cited(BaseModel):
    segment_id: Optional[str] = Field(None, description="Id of the segment the value was read from, e.g. S012")
    snippet: Optional[str] = Field(None, description="Verbatim text copied from that segment (max ~200 chars)")


class TextValue(Cited):
    value: Optional[str] = None


class NumValue(Cited):
    value: Optional[float] = None


class LLMFreight(Cited):
    basis: Literal["INCLUDED", "EXTRA_FIXED_TOTAL", "EXTRA_PER_UNIT", "EXTRA_PER_LOAD", "EXTRA_AT_ACTUALS", "UNSPECIFIED"]
    amount: Optional[float] = Field(None, description="Amount as written: total, per unit or per load depending on basis")
    loads: Optional[float] = Field(None, description="Number of loads/trucks if stated (EXTRA_PER_LOAD)")
    currency: Optional[str] = None


class LLMTax(Cited):
    basis: Literal["INCLUDED", "EXTRA", "UNSPECIFIED"]
    rate_pct: Optional[float] = None


class LLMHeader(BaseModel):
    vendor_name: TextValue
    quotation_ref: TextValue
    quotation_date: TextValue = Field(description="ISO date YYYY-MM-DD if determinable")
    currency: TextValue = Field(description="ISO 4217 code of the quoted prices, e.g. INR, USD")
    validity_days: NumValue
    payment_terms_text: TextValue
    payment_days: NumValue
    delivery_days_min: NumValue
    delivery_days_max: NumValue
    freight: LLMFreight
    tax: LLMTax


class LLMDiscount(Cited):
    kind: Literal["PERCENT", "FIXED_AMOUNT", "ALTERNATE_PRICE"]
    value: float
    scope: Literal["ORDER", "LINE"]
    rfx_line_ids: list[str] = Field(default_factory=list)
    condition_type: Literal["NONE", "ALL_QUOTED_ITEMS_AWARDED", "MIN_ORDER_VALUE", "EARLY_PAYMENT", "MIN_QUANTITY", "OTHER"]
    condition_value: Optional[float] = None
    condition_text: Optional[str] = None
    applies_to: Literal["BASIC_VALUE", "INVOICE_VALUE", "UNIT_PRICE"] = "BASIC_VALUE"
    already_included_in_prices: Optional[bool] = None


class LLMLine(Cited):
    vendor_line_ref: Optional[str] = None
    vendor_description: str
    rfx_line_id: Optional[str] = Field(None, description="Matched RFx line id (L01..L30) or null if no match")
    match_basis: str = Field(description="Short rationale: which attributes matched")
    match_confidence: Literal["HIGH", "MEDIUM", "LOW"]
    quantity: Optional[float] = None
    price: Optional[float] = Field(None, description="Price exactly as written; null if illegible/absent")
    price_currency: Optional[str] = None
    price_basis_text: Optional[str] = Field(None, description="Basis as written, e.g. 'Per 100 Nos', '/kg', 'Bundle of 25'")
    price_uom: PriceUOM
    units_per_price_uom: Optional[float] = Field(None, description="Pieces per price unit ONLY if the document states it")
    line_discount_pct: Optional[float] = None
    line_total: Optional[float] = None
    delivery_days: Optional[float] = None
    flags: list[LineFlag] = Field(default_factory=list)
    vendor_spec_note: Optional[str] = None

    @field_validator("rfx_line_id")
    @classmethod
    def _norm_id(cls, v):
        if v is None:
            return v
        v = v.strip().upper()
        return v or None


class LLMUnresolved(Cited):
    text: str
    rfx_line_ids: list[str] = Field(default_factory=list)
    reason: str


class LLMQuotation(BaseModel):
    header: LLMHeader
    discounts: list[LLMDiscount] = Field(default_factory=list)
    line_items: list[LLMLine]
    unresolved_references: list[LLMUnresolved] = Field(default_factory=list)
    document_warnings: list[str] = Field(default_factory=list)


class LLMCertificate(BaseModel):
    holder_name: TextValue
    standard: TextValue
    certificate_number: TextValue
    valid_until: TextValue = Field(description="ISO date YYYY-MM-DD")
    issuer: TextValue


# ------------------------------------------------------------------ validated output
class Check(BaseModel):
    name: str
    passed: Optional[bool]          # None = not applicable
    detail: str = ""
    penalty: float = 0.0


class ExceptionItem(BaseModel):
    code: str
    severity: Literal["INFO", "WARNING", "BLOCKING"]
    message: str
    rfx_line_id: Optional[str] = None
    segment_id: Optional[str] = None


class ValidatedLine(BaseModel):
    llm: LLMLine
    checks: list[Check]
    confidence: float
    band: Literal["HIGH", "MEDIUM", "LOW"]
    review_required: bool
    evidence_locator: Optional[dict[str, Any]] = None
    evidence_text: Optional[str] = None


class ValidatedField(BaseModel):
    name: str
    value: Any
    segment_id: Optional[str] = None
    snippet: Optional[str] = None
    checks: list[Check] = Field(default_factory=list)
    confidence: float = 100
    review_required: bool = False


class ExtractionOutcome(BaseModel):
    status: Literal["SUCCEEDED", "NEEDS_REVIEW", "FAILED", "AI_UNAVAILABLE"]
    document: Optional[SourceDocument] = None
    raw_llm: Optional[dict[str, Any]] = None
    quotation: Optional[LLMQuotation] = None
    header_fields: list[ValidatedField] = Field(default_factory=list)
    lines: list[ValidatedLine] = Field(default_factory=list)
    coverage: dict[str, str] = Field(default_factory=dict)   # rfx_line_id -> QUOTED/NOT_QUOTED/NEEDS_CLARIFICATION
    exceptions: list[ExceptionItem] = Field(default_factory=list)
    error: Optional[str] = None
    model: Optional[str] = None
    attempts: int = 0
