"""Deterministic normalization: every vendor line -> base currency per RFx UOM, ex-tax.

Every number carries a calculation trace and the assumptions behind it. Nothing here
calls an LLM. Rules:
  * missing quotes are NOT_QUOTED, never zero;
  * a unit conversion happens only with a known factor (standard pack, stated pack,
    or a disclosed weight model) — otherwise NOT_COMPARABLE with the reason;
  * conditional discounts are recorded, not applied, at line level (the optimizer
    applies them only in scenarios where the condition holds);
  * order-level freight is allocated pro-rata by value and the method is stated.
"""
from __future__ import annotations

from typing import Optional

from app.core.config import Settings, get_settings
from app.domain.normalized import (CalcStep, FxRate, NormalizationResult, NormalizedQuote, QuoteLineInput,
                                   VendorQuoteInput, VendorTermsSummary)
from app.normalization.weight import estimate_weight

STANDARD_PACK = {"HUNDRED": 100, "THOUSAND": 1000}
PACK_UOMS = {"BUNDLE", "BOX", "PACK", "CARTON"}
UNIT_FAMILY = {"pcs": {"PIECE"}, "set": {"SET"}, "roll": {"ROLL"}}
EQUIVALENT = {"pcs": {"SET"}, "set": {"PIECE"}}


class FxTable:
    def __init__(self, rates: list[dict | FxRate], base: str = "INR"):
        self.base = base
        self.rates = {(r["from_currency"] if isinstance(r, dict) else r.from_currency): FxRate(**r) if isinstance(r, dict) else r
                      for r in rates}

    def get(self, ccy: str) -> Optional[FxRate]:
        if ccy == self.base:
            return FxRate(from_currency=ccy, to_currency=ccy, rate=1.0, rate_date="-", source="identity", rate_type="IDENTITY")
        r = self.rates.get(ccy)
        return r if r and r.to_currency == self.base else None


def _fmt(x: float) -> str:
    return f"{x:,.4f}".rstrip("0").rstrip(".")


def convert_uom(line: QuoteLineInput, rfx_line: dict, steps: list[CalcStep]) -> tuple[Optional[float], Optional[str], Optional[str], list[str]]:
    """Return (factor: price-units per RFx-unit multiplier, conversion_kind, reason_if_impossible, assumptions).

    unit price per RFx UOM = vendor price × factor.
    """
    rfx_uom = rfx_line["uom"]
    u = line.price_uom
    if u in UNIT_FAMILY.get(rfx_uom, set()):
        steps.append(CalcStep(label="UOM", value=1, detail=f"Priced per {u.lower()} = RFx unit ({rfx_uom})"))
        return 1.0, "DIRECT", None, []
    if u in EQUIVALENT.get(rfx_uom, set()):
        steps.append(CalcStep(label="UOM", value=1, detail=f"Vendor 'per {u.lower()}' read as per {rfx_uom} (one unit each)"))
        return 1.0, "EQUIVALENT_UNIT", None, [f"Vendor priced per {u.lower()}; treated as per {rfx_uom}"]
    if u in STANDARD_PACK:
        n = line.units_per_price_uom or STANDARD_PACK[u]
        steps.append(CalcStep(label="UOM", value=1 / n, detail=f"Priced per {int(n)} units → ÷ {int(n)}"))
        return 1 / n, "STANDARD_PACK", None, []
    if u in PACK_UOMS:
        if line.units_per_price_uom and line.units_per_price_uom > 0:
            n = line.units_per_price_uom
            steps.append(CalcStep(label="UOM", value=1 / n, detail=f"Priced per {u.lower()} of {_fmt(n)} (stated in quote) → ÷ {_fmt(n)}"))
            return 1 / n, "STATED_PACK", None, []
        return None, None, f"Priced per {u.lower()} but the quote does not state units per {u.lower()}", []
    if u == "KG":
        w = estimate_weight(rfx_line["spec"])
        if not w:
            return None, None, "Priced per kg but this item has no geometry to estimate weight", []
        steps.append(CalcStep(label="Weight model", value=w.weight_kg, detail=w.explain()))
        return w.weight_kg, "DERIVED_WEIGHT", None, [
            f"Per-kg price converted with estimated weight {w.weight_kg * 1000:.0f} g/unit from RFx spec (confirm with vendor)"]
    return None, None, f"Cannot convert '{u}' to RFx unit '{rfx_uom}'", []


def normalize(rfx_lines: list[dict], vendor_quotes: list[VendorQuoteInput], fx: FxTable,
              settings: Settings | None = None) -> NormalizationResult:
    s = settings or get_settings()
    base = fx.base
    quotes: list[NormalizedQuote] = []
    summaries: list[VendorTermsSummary] = []
    by_line = {l["line_id"]: l for l in rfx_lines}

    for vq in vendor_quotes:
        fx_rate = fx.get(vq.currency) if vq.currency else None
        lines_by_id = {l.rfx_line_id: l for l in vq.lines}
        order_applied, conditional = [], []
        unconditional_pct = 0.0
        for d in vq.discounts:
            dd = d.model_dump()
            if d.already_included_in_prices:
                dd["note"] = "Stated as already included in prices — not applied again"
                conditional.append(dd)
                continue
            if d.kind == "ALTERNATE_PRICE":
                conditional.append(dd)
                continue
            if d.condition_type == "NONE" and d.kind == "PERCENT" and d.scope == "ORDER":
                unconditional_pct += d.value
                order_applied.append(dd)
            elif d.condition_type == "EARLY_PAYMENT" and s.apply_early_payment_discounts and d.kind == "PERCENT":
                unconditional_pct += d.value
                dd["note"] = "Applied: policy APPLY_EARLY_PAYMENT_DISCOUNTS=true"
                order_applied.append(dd)
            else:
                conditional.append(dd)

        vendor_lines: list[NormalizedQuote] = []
        for lid, rl in by_line.items():
            cov = vq.coverage.get(lid, "NOT_QUOTED")
            ln = lines_by_id.get(lid)
            nq = NormalizedQuote(vendor_id=vq.vendor_id, rfx_line_id=lid, status="NOT_QUOTED",
                                 rfx_uom=rl["uom"], quantity=rl["quantity"])
            if ln is None or cov in ("NOT_QUOTED", "NEEDS_CLARIFICATION"):
                nq.status = "NEEDS_CLARIFICATION" if cov == "NEEDS_CLARIFICATION" else "NOT_QUOTED"
                nq.reason = vq.clarification_notes.get(lid) or ("Vendor reference needs clarification" if nq.status == "NEEDS_CLARIFICATION"
                                                               else "Vendor did not quote this line")
                vendor_lines.append(nq)
                continue
            nq.original_price, nq.original_currency = ln.price, (ln.currency or vq.currency)
            nq.original_uom, nq.price_basis_text = ln.price_uom, ln.price_basis_text
            nq.flags, nq.confidence, nq.evidence = list(ln.flags), ln.confidence, ln.evidence
            nq.review_required = ln.review_required and not ln.reviewed_by_human
            nq.review_reasons = list(ln.review_reasons) if nq.review_required else []
            for c in vq.discounts:
                if c.kind == "ALTERNATE_PRICE" and lid in c.rfx_line_ids:
                    nq.conditional_offers.append({"kind": "ALTERNATE_PRICE", "value": c.value, "condition": c.condition_text})
            if ln.price is None:
                nq.status, nq.reason = "UNREADABLE", "Price present in document but not legible"
                nq.review_required = True
                vendor_lines.append(nq)
                continue
            steps = [CalcStep(label="Quoted", value=ln.price,
                              detail=f"{_fmt(ln.price)} {nq.original_currency or '?'} {ln.price_basis_text or ('per ' + ln.price_uom.lower())}")]
            factor, kind, why, assumptions = convert_uom(ln, rl, steps)
            if factor is None:
                nq.status, nq.reason = "NOT_COMPARABLE", why
                nq.trace = steps
                vendor_lines.append(nq)
                continue
            ccy = nq.original_currency
            rate = fx.get(ccy) if ccy else None
            if rate is None:
                nq.status, nq.reason = "NOT_COMPARABLE", f"No exchange rate configured for {ccy or 'unknown currency'}"
                nq.trace = steps
                vendor_lines.append(nq)
                continue
            unit = ln.price * factor
            steps.append(CalcStep(label=f"Per {rl['uom']}", value=unit, detail=f"{_fmt(ln.price)} × {_fmt(factor)} = {_fmt(unit)} {ccy}"))
            if rate.rate != 1.0:
                unit *= rate.rate
                steps.append(CalcStep(label="FX", value=unit,
                                      detail=f"× {rate.rate} {ccy}→{base} ({rate.source}, {rate.rate_date})"))
                assumptions.append(f"FX {ccy}→{base} {rate.rate} is an {rate.rate_type.replace('_', ' ').lower()} rate dated {rate.rate_date}")
            if ln.line_discount_pct:
                unit *= (1 - ln.line_discount_pct / 100)
                steps.append(CalcStep(label="Line discount", value=unit, detail=f"− {ln.line_discount_pct}%"))
            if unconditional_pct:
                unit *= (1 - unconditional_pct / 100)
                steps.append(CalcStep(label="Order discount", value=unit, detail=f"− {unconditional_pct}% (unconditional)"))
            if vq.tax_basis == "INCLUDED" and s.compare_ex_tax:
                if vq.tax_rate_pct:
                    unit /= (1 + vq.tax_rate_pct / 100)
                    steps.append(CalcStep(label="Remove GST", value=unit, detail=f"÷ (1 + {vq.tax_rate_pct}%) to compare ex-GST"))
                else:
                    nq.review_required = True
                    nq.review_reasons.append("Price stated tax-inclusive but tax rate unknown")
            if kind == "DERIVED_WEIGHT" and s.derived_weight_requires_review and "DERIVED_WEIGHT" not in ln.accepted_assumptions:
                nq.review_required = True
                nq.review_reasons.append("Per-kg price converted with an estimated box weight — confirm or accept assumption")
            nq.status, nq.conversion_kind = "QUOTED", kind
            nq.unit_price_base = round(unit, 4)
            nq.line_value_base = round(unit * rl["quantity"], 2)
            nq.assumptions = assumptions
            steps.append(CalcStep(label="Comparable unit price", value=nq.unit_price_base,
                                  detail=f"{base} per {rl['uom']}, ex-GST"))
            steps.append(CalcStep(label="Line value", value=nq.line_value_base,
                                  detail=f"× RFx qty {rl['quantity']:,} {rl['uom']}"))
            nq.trace = steps
            vendor_lines.append(nq)

        # ---- freight → landed cost
        comparable = [q for q in vendor_lines if q.comparable]
        total_value = sum(q.line_value_base for q in comparable) or 0.0
        fr_rate = fx.get(vq.freight_currency or vq.currency or base)
        freight_total, freight_note = None, ""
        fb = vq.freight_basis
        if fb == "INCLUDED":
            freight_total, freight_note = 0.0, "Freight included in prices"
        elif fb in ("EXTRA_FIXED_TOTAL", "EXTRA_PER_LOAD") and vq.freight_amount is not None and fr_rate:
            if fb == "EXTRA_PER_LOAD" and not vq.freight_loads:
                fb = "EXTRA_AT_ACTUALS"
            else:
                freight_total = vq.freight_amount * (vq.freight_loads or 1) * fr_rate.rate
                freight_note = (f"{_fmt(vq.freight_amount)} × {_fmt(vq.freight_loads)} loads" if fb == "EXTRA_PER_LOAD"
                                else f"{_fmt(vq.freight_amount)} fixed") + f" = {base} {freight_total:,.0f}, allocated pro-rata by line value"
        for q in comparable:
            if fb == "INCLUDED":
                q.freight_per_unit, q.freight_method = 0.0, "Included in price"
            elif fb == "EXTRA_PER_UNIT" and vq.freight_amount is not None and fr_rate:
                q.freight_per_unit = vq.freight_amount * fr_rate.rate
                q.freight_method = f"Vendor charges {_fmt(vq.freight_amount)} {vq.freight_currency or vq.currency} per unit"
            elif freight_total is not None and total_value:
                share = freight_total / total_value
                q.freight_per_unit = q.unit_price_base * share
                q.freight_method = (f"Order freight {base} {freight_total:,.0f} allocated pro-rata by value "
                                    f"(+{share * 100:.2f}%); actual loads depend on awarded volume")
                q.assumptions.append("Order-level freight allocated pro-rata by line value")
            else:
                pct = s.freight_at_actuals_assumed_pct
                q.freight_per_unit = q.unit_price_base * pct / 100
                q.freight_method = (f"Freight {'at actuals' if fb == 'EXTRA_AT_ACTUALS' else 'not stated'} — "
                                    f"ASSUMED {pct}% of base price (configurable)")
                q.assumptions.append(f"Freight assumed at {pct}% of base price (vendor: {'at actuals' if fb == 'EXTRA_AT_ACTUALS' else 'not stated'})")
            q.landed_unit_price = round(q.unit_price_base + q.freight_per_unit, 4)
            q.landed_line_value = round(q.landed_unit_price * q.quantity, 2)
            q.trace.append(CalcStep(label="Freight", value=round(q.freight_per_unit, 4), detail=q.freight_method))
            q.trace.append(CalcStep(label="Landed unit price", value=q.landed_unit_price, detail=f"{base} per {q.rfx_uom}, ex-GST"))
        if fb == "EXTRA_PER_UNIT" and vq.freight_amount is not None and fr_rate:
            freight_total = sum(q.freight_per_unit * q.quantity for q in comparable)
            freight_note = f"{_fmt(vq.freight_amount)} per unit"
        if fb in ("EXTRA_AT_ACTUALS", "UNSPECIFIED"):
            freight_note = f"Not quantified by vendor; landed cost uses assumed {s.freight_at_actuals_assumed_pct}%"

        counts: dict[str, int] = {}
        for q in vendor_lines:
            counts[q.status] = counts.get(q.status, 0) + 1
        quoted = sum(1 for q in vendor_lines if q.status in ("QUOTED", "NOT_COMPARABLE", "UNREADABLE"))
        summaries.append(VendorTermsSummary(
            vendor_id=vq.vendor_id, vendor_name=vq.vendor_name, currency=vq.currency, fx=fx_rate,
            freight_basis=vq.freight_basis, freight_total_base=freight_total, freight_note=freight_note,
            tax_basis=vq.tax_basis, tax_rate_pct=vq.tax_rate_pct, payment_days=vq.payment_days,
            delivery_days_min=vq.delivery_days_min, delivery_days_max=vq.delivery_days_max, validity_days=vq.validity_days,
            order_discounts_applied=order_applied, conditional_discounts=conditional, coverage_counts=counts,
            quoted_lines=quoted, comparable_lines=len(comparable), coverage_pct=round(quoted / len(rfx_lines) * 100, 1),
            review_required_lines=sum(1 for q in vendor_lines if q.review_required)))
        quotes.extend(vendor_lines)

    policy = {"base_currency": base, "compare_ex_tax": s.compare_ex_tax,
              "apply_early_payment_discounts": s.apply_early_payment_discounts,
              "freight_at_actuals_assumed_pct": s.freight_at_actuals_assumed_pct,
              "derived_weight_requires_review": s.derived_weight_requires_review}
    return NormalizationResult(base_currency=base, quotes=quotes, vendors=summaries, policy=policy)
