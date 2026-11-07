"""Turn a validated extraction (+ optional human corrections) into normalization input."""
from __future__ import annotations

from typing import Any, Optional

from app.domain.extraction import ExtractionOutcome
from app.domain.normalized import DiscountInput, Evidence, QuoteLineInput, VendorQuoteInput


def outcome_to_vendor_input(outcome: ExtractionOutcome, vendor_id: str, vendor_name: str,
                            document_id: Optional[str] = None,
                            corrections: Optional[dict[str, dict[str, Any]]] = None) -> VendorQuoteInput:
    """corrections: {rfx_line_id: {"price": .., "price_uom": .., "units_per_price_uom": .., "currency": ..,
    "status": "NOT_QUOTED"|"QUOTED", "accepted_assumptions": [...], "reviewed": True}}"""
    q = outcome.quotation
    corrections = corrections or {}
    if q is None:
        return VendorQuoteInput(vendor_id=vendor_id, vendor_name=vendor_name, currency=None,
                                coverage={}, clarification_notes={})
    h = q.header
    ccy = (h.currency.value or "").upper() or None
    doc = outcome.document

    def ev(seg_id, locator=None, text=None):
        seg = doc.segment(seg_id) if doc else None
        return Evidence(document_id=document_id, filename=doc.filename if doc else None, segment_id=seg_id,
                        locator=locator or (seg.locator if seg else None), text=text or (seg.text if seg else None))

    lines: list[QuoteLineInput] = []
    seen = set()
    for v in sorted(outcome.lines, key=lambda v: -v.confidence):
        l = v.llm
        if not l.rfx_line_id or l.rfx_line_id in seen:
            continue
        seen.add(l.rfx_line_id)
        reasons = [c.detail for c in sorted(v.checks, key=lambda c: -c.penalty) if c.penalty >= 10][:3]
        qi = QuoteLineInput(rfx_line_id=l.rfx_line_id, price=l.price, currency=(l.price_currency or ccy),
                            price_uom=l.price_uom.value, price_basis_text=l.price_basis_text,
                            units_per_price_uom=l.units_per_price_uom, line_discount_pct=l.line_discount_pct,
                            vendor_description=l.vendor_description, flags=[f.value for f in l.flags],
                            confidence=v.confidence, review_required=v.review_required, review_reasons=reasons,
                            evidence=ev(l.segment_id, v.evidence_locator, v.evidence_text))
        c = corrections.get(l.rfx_line_id)
        if c:
            upd = {k: c[k] for k in ("price", "price_uom", "units_per_price_uom", "currency", "line_discount_pct") if k in c}
            qi = qi.model_copy(update=upd)
            qi.reviewed_by_human = bool(c.get("reviewed", True))
            qi.accepted_assumptions = list(c.get("accepted_assumptions", []))
        lines.append(qi)

    coverage = dict(outcome.coverage)
    for lid, c in corrections.items():
        if c.get("status") in ("NOT_QUOTED", "QUOTED", "NEEDS_CLARIFICATION"):
            coverage[lid] = c["status"]
            if c["status"] == "QUOTED" and lid not in {x.rfx_line_id for x in lines} and c.get("price") is not None:
                lines.append(QuoteLineInput(rfx_line_id=lid, price=c["price"], currency=c.get("currency", ccy),
                                            price_uom=c.get("price_uom", "PIECE"),
                                            units_per_price_uom=c.get("units_per_price_uom"),
                                            reviewed_by_human=True, confidence=100,
                                            evidence=Evidence(document_id=document_id, text="Entered manually by reviewer")))
    notes = {}
    for u in q.unresolved_references:
        for lid in u.rfx_line_ids:
            notes[lid] = f"Vendor wrote “{u.text[:80]}” — {u.reason}"
    disc = [DiscountInput(kind=d.kind, value=d.value, scope=d.scope, rfx_line_ids=d.rfx_line_ids,
                          condition_type=d.condition_type, condition_value=d.condition_value,
                          condition_text=d.condition_text, already_included_in_prices=d.already_included_in_prices,
                          evidence=ev(d.segment_id)) for d in q.discounts]
    return VendorQuoteInput(
        vendor_id=vendor_id, vendor_name=vendor_name, currency=ccy,
        freight_basis=h.freight.basis, freight_amount=h.freight.amount, freight_loads=h.freight.loads,
        freight_currency=(h.freight.currency or ccy), tax_basis=h.tax.basis, tax_rate_pct=h.tax.rate_pct,
        payment_days=h.payment_days.value, delivery_days_min=h.delivery_days_min.value,
        delivery_days_max=h.delivery_days_max.value, validity_days=h.validity_days.value,
        lines=lines, coverage=coverage, discounts=disc, clarification_notes=notes)
