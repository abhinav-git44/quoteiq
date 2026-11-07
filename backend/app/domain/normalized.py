"""Inputs and outputs of the deterministic normalization engine."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

QuoteStatus = Literal["QUOTED", "NOT_QUOTED", "NOT_COMPARABLE", "NEEDS_CLARIFICATION", "UNREADABLE"]


class Evidence(BaseModel):
    document_id: Optional[str] = None
    filename: Optional[str] = None
    segment_id: Optional[str] = None
    locator: Optional[dict[str, Any]] = None
    text: Optional[str] = None


class QuoteLineInput(BaseModel):
    """One vendor line after extraction (+ any human correction). Values exactly as quoted."""
    rfx_line_id: str
    price: Optional[float]
    currency: Optional[str]
    price_uom: str                        # PriceUOM value
    price_basis_text: Optional[str] = None
    units_per_price_uom: Optional[float] = None
    line_discount_pct: Optional[float] = None
    vendor_description: Optional[str] = None
    flags: list[str] = Field(default_factory=list)
    confidence: float = 100
    review_required: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    reviewed_by_human: bool = False
    accepted_assumptions: list[str] = Field(default_factory=list)   # e.g. ["DERIVED_WEIGHT"]
    evidence: Evidence = Field(default_factory=Evidence)


class DiscountInput(BaseModel):
    kind: Literal["PERCENT", "FIXED_AMOUNT", "ALTERNATE_PRICE"]
    value: float
    scope: Literal["ORDER", "LINE"]
    rfx_line_ids: list[str] = Field(default_factory=list)
    condition_type: str = "NONE"
    condition_value: Optional[float] = None
    condition_text: Optional[str] = None
    already_included_in_prices: Optional[bool] = None
    evidence: Evidence = Field(default_factory=Evidence)


class VendorQuoteInput(BaseModel):
    vendor_id: str
    vendor_name: str
    currency: Optional[str]
    freight_basis: str = "UNSPECIFIED"
    freight_amount: Optional[float] = None
    freight_loads: Optional[float] = None
    freight_currency: Optional[str] = None
    tax_basis: str = "UNSPECIFIED"
    tax_rate_pct: Optional[float] = None
    payment_days: Optional[float] = None
    delivery_days_min: Optional[float] = None
    delivery_days_max: Optional[float] = None
    validity_days: Optional[float] = None
    lines: list[QuoteLineInput] = Field(default_factory=list)
    coverage: dict[str, str] = Field(default_factory=dict)   # rfx_line_id -> QUOTED/NOT_QUOTED/NEEDS_CLARIFICATION/UNREADABLE
    discounts: list[DiscountInput] = Field(default_factory=list)
    clarification_notes: dict[str, str] = Field(default_factory=dict)  # rfx_line_id -> reason


class FxRate(BaseModel):
    from_currency: str
    to_currency: str
    rate: float
    rate_date: str
    source: str
    rate_type: str


class CalcStep(BaseModel):
    label: str
    value: Optional[float] = None
    detail: str = ""


class NormalizedQuote(BaseModel):
    vendor_id: str
    rfx_line_id: str
    status: QuoteStatus
    reason: Optional[str] = None
    original_price: Optional[float] = None
    original_currency: Optional[str] = None
    original_uom: Optional[str] = None
    price_basis_text: Optional[str] = None
    conversion_kind: Optional[Literal["DIRECT", "STANDARD_PACK", "STATED_PACK", "DERIVED_WEIGHT", "EQUIVALENT_UNIT"]] = None
    rfx_uom: str = "pcs"
    quantity: float = 0
    unit_price_base: Optional[float] = None       # base currency per RFx UOM, ex-tax, after unconditional discounts
    line_value_base: Optional[float] = None
    freight_per_unit: Optional[float] = None
    freight_method: Optional[str] = None
    landed_unit_price: Optional[float] = None
    landed_line_value: Optional[float] = None
    confidence: float = 100
    review_required: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    conditional_offers: list[dict[str, Any]] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    trace: list[CalcStep] = Field(default_factory=list)
    evidence: Evidence = Field(default_factory=Evidence)

    @property
    def comparable(self) -> bool:
        return self.status == "QUOTED" and self.unit_price_base is not None


class VendorTermsSummary(BaseModel):
    vendor_id: str
    vendor_name: str
    currency: Optional[str]
    fx: Optional[FxRate] = None
    freight_basis: str
    freight_total_base: Optional[float] = None
    freight_note: str = ""
    tax_basis: str
    tax_rate_pct: Optional[float] = None
    payment_days: Optional[float] = None
    delivery_days_min: Optional[float] = None
    delivery_days_max: Optional[float] = None
    validity_days: Optional[float] = None
    order_discounts_applied: list[dict[str, Any]] = Field(default_factory=list)
    conditional_discounts: list[dict[str, Any]] = Field(default_factory=list)
    coverage_counts: dict[str, int] = Field(default_factory=dict)
    quoted_lines: int = 0
    comparable_lines: int = 0
    coverage_pct: float = 0
    review_required_lines: int = 0


class NormalizationResult(BaseModel):
    base_currency: str
    quotes: list[NormalizedQuote]
    vendors: list[VendorTermsSummary]
    policy: dict[str, Any]

    def get(self, vendor_id: str, line_id: str) -> Optional[NormalizedQuote]:
        for q in self.quotes:
            if q.vendor_id == vendor_id and q.rfx_line_id == line_id:
                return q
        return None
