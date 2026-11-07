"""Restricted analyst tools. The model can only call these; there is no SQL or code execution.

Every tool validates its arguments (Pydantic), reads the AnalysisContext, and returns
{"result": <compact JSON for the model>, "displays": [<tables/charts for the UI>]}.
"""
from __future__ import annotations

from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

from app.analyst.context import AnalysisContext
from app.ai.llm import inline_schema
from app.normalization.engine import normalize
from app.optimization.award import AwardParams, build_scenario, compare_savings

CostBasis = Literal["base", "landed"]


class ToolError(ValueError):
    pass


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def _vid(ctx: AnalysisContext, ref: str) -> str:
    v = ctx.resolve_vendor(ref)
    if not v:
        raise ToolError(f"Unknown vendor '{ref}'. Known: " + ", ".join(f"{v['vendor_id']} {v['name']}" for v in ctx.vendors))
    return v


def _price(q, basis):
    return q.landed_unit_price if basis == "landed" else q.unit_price_base


def _elig(ctx, vid):
    e = ctx.eligibility.get(vid)
    return e.status if e else "PENDING"


def table(title, columns, rows, note=None):
    d = {"type": "table", "title": title, "columns": columns, "rows": rows}
    if note:
        d["note"] = note
    return d


def chart(title, kind, x, series, y_label=None, note=None):
    d = {"type": "chart", "chart": kind, "title": title, "x": x, "series": series}
    if y_label:
        d["y_label"] = y_label
    if note:
        d["note"] = note
    return d


# ------------------------------------------------------------------ tool arg models
class NoArgs(BaseModel):
    pass


class VendorFilter(BaseModel):
    vendor_ids: list[str] = Field(default_factory=list, description="Vendor ids or names; empty = all")


class LineComparisonArgs(BaseModel):
    line_ids: list[str] = Field(default_factory=list, description="RFx line ids (L01..L30); empty = all")
    cost_basis: CostBasis = "base"
    eligible_only: bool = Field(False, description="Only consider quality-eligible vendors when picking the lowest")


class VendorDetailArgs(BaseModel):
    vendor_id: str
    line_ids: list[str] = Field(default_factory=list)
    include_trace: bool = False


class OneVendorOpt(BaseModel):
    vendor_id: Optional[str] = None


class ExceptionArgs(BaseModel):
    vendor_id: Optional[str] = None
    only_affecting_lines: list[str] = Field(default_factory=list)


class NormCostArgs(BaseModel):
    vendor_id: str
    line_id: str
    fx_rate_override: Optional[float] = Field(None, description="What-if FX rate to base currency for this vendor's currency")
    units_per_price_uom_override: Optional[float] = Field(None, description="What-if pack size for per-box/bundle prices")
    freight_pct_override: Optional[float] = Field(None, description="What-if freight % for freight-at-actuals vendors")


class CompareVendorArgs(BaseModel):
    vendor_ids: list[str] = Field(default_factory=list, description="Two or more vendors; empty = all")
    cost_basis: CostBasis = "base"
    common_lines_only: bool = Field(True, description="Compare only lines every selected vendor validly quoted")


class OptimizeArgs(BaseModel):
    strategy: Literal["SINGLE_VENDOR", "LOWEST_PRICE_SPLIT", "BALANCED"] = "LOWEST_PRICE_SPLIT"
    cost_basis: CostBasis = "base"
    eligible_only: bool = Field(True, description="Restrict to vendors whose quality status is ELIGIBLE")
    include_pending: bool = Field(False, description="Also allow vendors whose quality evaluation is PENDING")
    include_vendor_ids: list[str] = Field(default_factory=list)
    exclude_vendor_ids: list[str] = Field(default_factory=list)
    exclude_unverified: bool = Field(False, description="Ignore quotes still awaiting human verification")
    max_vendors: Optional[int] = Field(None, ge=1, le=5)
    max_share_pct: Optional[float] = Field(None, gt=0, le=100)
    single_vendor_id: Optional[str] = None
    discount_aware: bool = Field(True, description="Search award patterns that earn conditional 'all items' discounts")
    weights: Optional[dict[str, float]] = Field(None, description="BALANCED only: weights for quality, delivery, history")


class SavingsArgs(BaseModel):
    scenario_id: str
    baseline: str = Field("best_single_vendor", description="'best_single_vendor', 'target_price', or another scenario_id")


class ComparisonTableArgs(BaseModel):
    line_ids: list[str] = Field(default_factory=list)
    vendor_ids: list[str] = Field(default_factory=list)
    value: Literal["unit_price", "landed_unit_price", "line_value", "original"] = "unit_price"
    title: Optional[str] = None


class ChartArgs(BaseModel):
    chart: Literal["vendor_totals_common_lines", "coverage", "price_spread", "scenario_shares", "scenario_comparison", "quality_scores"]
    scenario_ids: list[str] = Field(default_factory=list)
    line_ids: list[str] = Field(default_factory=list)
    cost_basis: CostBasis = "base"


class ExportArgs(BaseModel):
    kind: Literal["comparison_xlsx", "award_pdf", "exceptions_xlsx", "quality_pdf", "audit_csv"]
    scenario_id: Optional[str] = None


class ClarifyArgs(BaseModel):
    vendor_id: str


# ------------------------------------------------------------------ implementations
def get_rfx_summary(ctx: AnalysisContext, a: NoArgs):
    target = sum((l.get("target_price_inr") or 0) * l["quantity"] for l in ctx.lines)
    subs = {vid: x.get("status") for vid, x in ctx.extraction.items()}
    return {"result": {
        "rfx": {k: ctx.rfx.get(k) for k in ("reference", "title", "category", "issue_date", "submission_deadline",
                                             "currency", "required_delivery_days", "delivery_location")},
        "line_count": len(ctx.lines), "target_value_at_last_contract_rates": _r(target),
        "vendors_invited": [{"vendor_id": v["vendor_id"], "name": v["name"], "format": v.get("submission_format")} for v in ctx.vendors],
        "extraction_status": subs, "normalization_policy": ctx.norm.policy,
        "fx_rates": ctx.fx_rates}, "displays": []}


def get_vendor_summary(ctx: AnalysisContext, a: VendorFilter):
    ids = [_vid(ctx, v) for v in a.vendor_ids] or [v["vendor_id"] for v in ctx.vendors]
    rows, out = [], []
    for vs in ctx.norm.vendors:
        if vs.vendor_id not in ids:
            continue
        qs = [q for q in ctx.norm.quotes if q.vendor_id == vs.vendor_id]
        tot = sum(q.line_value_base for q in qs if q.comparable)
        lowest = 0
        for l in ctx.lines:
            cands = [q for q in ctx.norm.quotes if q.rfx_line_id == l["line_id"] and q.comparable]
            if cands and min(cands, key=lambda q: q.unit_price_base).vendor_id == vs.vendor_id:
                lowest += 1
        el = ctx.eligibility.get(vs.vendor_id)
        meta = next(v for v in ctx.vendors if v["vendor_id"] == vs.vendor_id)
        rec = {"vendor_id": vs.vendor_id, "name": vs.vendor_name, "currency": vs.currency,
               "coverage": vs.coverage_counts, "quoted_lines": vs.quoted_lines, "comparable_lines": vs.comparable_lines,
               "coverage_pct": vs.coverage_pct, "total_base_on_own_comparable_lines": _r(tot),
               "lowest_price_lines_all_vendors": lowest,
               "quality_status": el.status if el else "PENDING", "quality_score": el.quality_score if el else None,
               "quality_reasons": el.reasons if el else [],
               "payment_days": vs.payment_days, "delivery_days": [vs.delivery_days_min, vs.delivery_days_max],
               "freight": {"basis": vs.freight_basis, "note": vs.freight_note, "total_base": _r(vs.freight_total_base)},
               "tax_basis": vs.tax_basis, "conditional_discounts": vs.conditional_discounts,
               "lines_needing_review": vs.review_required_lines, "historical_score": meta.get("historical_score"),
               "fx": vs.fx.model_dump() if vs.fx and vs.fx.rate_type != "IDENTITY" else None}
        out.append(rec)
        rows.append([vs.vendor_name, f"{vs.quoted_lines}/{len(ctx.lines)}", vs.comparable_lines, _r(tot, 0),
                     rec["quality_status"], vs.review_required_lines, vs.freight_basis.replace("_", " ").lower(),
                     vs.payment_days])
    return {"result": {"vendors": out, "note": "Totals cover different line sets when coverage differs — not directly comparable."},
            "displays": [table("Vendor summary", ["Vendor", "Quoted", "Comparable", "Total on own comparable lines (₹)",
                                                  "Quality", "Lines to verify", "Freight", "Payment days"], rows,
                               "Totals are not like-for-like when coverage differs.")]}


def get_line_item_comparison(ctx: AnalysisContext, a: LineComparisonArgs):
    ids = [x.upper() for x in a.line_ids] or [l["line_id"] for l in ctx.lines]
    names = ctx.names
    vids = [v["vendor_id"] for v in ctx.vendors]
    out, rows = [], []
    for lid in ids:
        l = ctx.line(lid)
        if not l:
            raise ToolError(f"Unknown line {lid}")
        cells, best = {}, None
        for vid in vids:
            q = ctx.norm.get(vid, lid)
            p = _price(q, a.cost_basis) if q and q.comparable else None
            cells[vid] = {"status": q.status if q else "NOT_QUOTED", "unit_price": _r(p, 4),
                          "needs_verification": bool(q and q.review_required), "eligible": _elig(ctx, vid)}
            if p is not None and (not a.eligible_only or _elig(ctx, vid) == "ELIGIBLE"):
                if best is None or p < best[1]:
                    best = (vid, p)
        valid = [c["unit_price"] for c in cells.values() if c["unit_price"] is not None]
        spread = _r(100 * (max(valid) - min(valid)) / min(valid), 1) if len(valid) > 1 else None
        compact = {vid: (c["unit_price"] if not c["needs_verification"] else f"{c['unit_price']}*") if c["unit_price"] is not None
                   else c["status"] for vid, c in cells.items()}
        out.append({"line_id": lid, "name": l["name"], "qty": l["quantity"], "uom": l["uom"],
                    "target": l.get("target_price_inr"), "unit_price_by_vendor": compact,
                    "lowest_vendor": best[0] if best else None, "lowest_unit_price": _r(best[1], 4) if best else None,
                    "lowest_line_value": _r(best[1] * l["quantity"]) if best else None,
                    "spread_pct": spread,
                    "comment": None if best else "No valid comparable quote" + (" from an eligible vendor" if a.eligible_only else "")})
        def fmt(c):
            if c["unit_price"] is None:
                return c["status"].replace("_", " ").title()
            return f"{c['unit_price']:,.2f}" + (" ⚠" if c["needs_verification"] else "")
        rows.append([lid, l["name"], f"{l['quantity']:,} {l['uom']}"] + [fmt(cells[v]) for v in vids]
                    + [names.get(best[0]) if best else "—", _r(best[1] * l["quantity"], 0) if best else None])
    basis = "landed (incl. freight)" if a.cost_basis == "landed" else "base"
    return {"result": {"cost_basis": a.cost_basis, "eligible_only": a.eligible_only,
                       "legend": "unit price in base currency per RFx unit; '*' = awaiting human verification; text = status",
                       "lines": out,
                       "eligibility": {vid: _elig(ctx, vid) for vid in vids}},
            "displays": [table(f"Line-by-line comparison — {basis} unit price, ₹ ex-GST"
                               + (" (eligible vendors only)" if a.eligible_only else ""),
                               ["Line", "Item", "Qty"] + [names[v] for v in vids] + ["Lowest", "Lowest line value (₹)"], rows,
                               "⚠ = value awaiting human verification")]}


def get_vendor_quotation_details(ctx: AnalysisContext, a: VendorDetailArgs):
    vid = _vid(ctx, a.vendor_id)
    ids = [x.upper() for x in a.line_ids] or [l["line_id"] for l in ctx.lines]
    out = []
    for lid in ids:
        q = ctx.norm.get(vid, lid)
        if not q:
            continue
        rec = {"line_id": lid, "status": q.status, "reason": q.reason, "original": {
            "price": q.original_price, "currency": q.original_currency, "uom": q.original_uom, "basis": q.price_basis_text},
            "conversion": q.conversion_kind, "unit_price_base": _r(q.unit_price_base, 4),
            "landed_unit_price": _r(q.landed_unit_price, 4), "confidence": _r(q.confidence, 0),
            "needs_verification": q.review_required, "review_reasons": q.review_reasons, "flags": q.flags,
            "assumptions": q.assumptions, "conditional_offers": q.conditional_offers,
            "evidence": {"file": q.evidence.filename, "segment": q.evidence.segment_id,
                         "where": {k: v for k, v in (q.evidence.locator or {}).items() if k != "bbox"},
                         "source_text": (q.evidence.text or "")[:160]}}
        if a.include_trace:
            rec["trace"] = [s.model_dump() for s in q.trace]
        out.append(rec)
    return {"result": {"vendor_id": vid, "vendor": ctx.names[vid], "lines": out}, "displays": []}


def get_quality_eligibility(ctx: AnalysisContext, a: OneVendorOpt):
    ids = [_vid(ctx, a.vendor_id)] if a.vendor_id else [v["vendor_id"] for v in ctx.vendors]
    out, rows = [], []
    for vid in ids:
        e = ctx.eligibility.get(vid)
        if not e:
            out.append({"vendor_id": vid, "status": "PENDING", "reasons": ["Not evaluated"]}); continue
        out.append({"vendor_id": vid, "vendor": ctx.names[vid], "status": e.status, "quality_score": e.quality_score,
                    "reasons": e.reasons,
                    "answers": [{"qid": x.qid, "mandatory": x.mandatory, "answer": x.answer, "status": x.status,
                                 "reason": x.reason} for x in e.answers if x.status != "PASS" or a.vendor_id]})
        rows.append([ctx.names[vid], e.status, e.quality_score, "; ".join(e.reasons)[:140]])
    return {"result": {"policy": "Eligible only if every mandatory question PASSes; missing mandatory answers stay PENDING.",
                       "vendors": out},
            "displays": [table("Quality questionnaire eligibility", ["Vendor", "Status", "Score", "Why"], rows)]}


def get_missing_quotations(ctx: AnalysisContext, a: OneVendorOpt):
    ids = [_vid(ctx, a.vendor_id)] if a.vendor_id else [v["vendor_id"] for v in ctx.vendors]
    out, rows = [], []
    for vid in ids:
        qs = [q for q in ctx.norm.quotes if q.vendor_id == vid]
        gaps = [{"line_id": q.rfx_line_id, "status": q.status, "reason": q.reason} for q in qs if q.status != "QUOTED"]
        quoted = sum(1 for q in qs if q.status in ("QUOTED", "NOT_COMPARABLE", "UNREADABLE"))
        out.append({"vendor_id": vid, "vendor": ctx.names[vid], "quoted": quoted, "of": len(ctx.lines),
                    "comparable": sum(1 for q in qs if q.comparable), "gaps": gaps})
        by = {}
        for g in gaps:
            by.setdefault(g["status"], []).append(g["line_id"])
        rows.append([ctx.names[vid], f"{quoted}/{len(ctx.lines)}", sum(1 for q in qs if q.comparable),
                     ", ".join(by.get("NOT_QUOTED", [])) or "—", ", ".join(by.get("NEEDS_CLARIFICATION", [])) or "—",
                     ", ".join(by.get("NOT_COMPARABLE", []) + by.get("UNREADABLE", [])) or "—"])
    return {"result": {"vendors": out},
            "displays": [table("Quotation coverage", ["Vendor", "Quoted", "Comparable", "Not quoted", "Needs clarification",
                                                      "Not comparable / unreadable"], rows)]}


def get_extraction_exceptions(ctx: AnalysisContext, a: ExceptionArgs):
    ids = [_vid(ctx, a.vendor_id)] if a.vendor_id else [v["vendor_id"] for v in ctx.vendors]
    filt = {x.upper() for x in a.only_affecting_lines}
    out, rows = [], []
    for vid in ids:
        for q in ctx.norm.quotes:
            if q.vendor_id != vid or not (q.review_required or q.status in ("UNREADABLE", "NOT_COMPARABLE", "NEEDS_CLARIFICATION")):
                continue
            if filt and q.rfx_line_id not in filt:
                continue
            why = q.review_reasons or ([q.reason] if q.reason else [])
            rec = {"vendor_id": vid, "line_id": q.rfx_line_id, "status": q.status, "confidence": _r(q.confidence, 0),
                   "why": why, "file": q.evidence.filename, "segment": q.evidence.segment_id,
                   "source_text": (q.evidence.text or "")[:140]}
            out.append(rec)
            rows.append([ctx.names[vid], q.rfx_line_id, q.status.replace("_", " ").title(), _r(q.confidence, 0),
                         "; ".join(why)[:150], f"{q.evidence.filename or ''} {q.evidence.segment_id or ''}".strip()])
        for e in ctx.extraction.get(vid, {}).get("exceptions", []):
            if e.get("rfx_line_id") or e.get("code") in ("LOW_CONFIDENCE", "UNREADABLE_PRICE"):
                continue
            out.append({"vendor_id": vid, "document_level": True, **e})
            rows.append([ctx.names[vid], "—", e.get("severity"), None, e.get("message", "")[:150], e.get("segment_id") or ""])
    return {"result": {"items": out, "count": len(out)},
            "displays": [table("Items requiring verification or clarification",
                               ["Vendor", "Line", "Status", "Confidence", "Why", "Source"], rows)]}


def calculate_normalized_cost(ctx: AnalysisContext, a: NormCostArgs):
    vid = _vid(ctx, a.vendor_id)
    lid = a.line_id.upper()
    vi = next((v for v in ctx.vendor_inputs if v.vendor_id == vid), None)
    if vi is None or not ctx.line(lid):
        raise ToolError("Unknown vendor or line")
    vi = vi.model_copy(deep=True)
    if a.units_per_price_uom_override:
        for l in vi.lines:
            if l.rfx_line_id == lid:
                l.units_per_price_uom = a.units_per_price_uom_override
    fx_over = {vi.currency: a.fx_rate_override} if (a.fx_rate_override and vi.currency) else None
    settings = ctx.settings
    if a.freight_pct_override is not None:
        from dataclasses import replace
        settings = replace(settings, freight_at_actuals_assumed_pct=a.freight_pct_override)
    res = normalize([ctx.line(lid)], [vi], ctx.fx(fx_over), settings)
    q = res.quotes[0]
    base = ctx.norm.get(vid, lid)
    whatif = bool(a.fx_rate_override or a.units_per_price_uom_override or a.freight_pct_override is not None)
    return {"result": {"vendor": ctx.names[vid], "line_id": lid, "what_if": whatif, "status": q.status, "reason": q.reason,
                       "unit_price_base": _r(q.unit_price_base, 4), "landed_unit_price": _r(q.landed_unit_price, 4),
                       "line_value_base": _r(q.line_value_base), "persisted_unit_price_base": _r(base.unit_price_base, 4) if base else None,
                       "trace": [s.model_dump() for s in q.trace], "assumptions": q.assumptions,
                       "note": "What-if values are NOT persisted." if whatif else "Matches persisted normalization."}, "displays": []}


def compare_vendor_costs(ctx: AnalysisContext, a: CompareVendorArgs):
    ids = [_vid(ctx, v) for v in a.vendor_ids] or [v["vendor_id"] for v in ctx.vendors]
    valid = {vid: {q.rfx_line_id for q in ctx.norm.quotes if q.vendor_id == vid and q.comparable} for vid in ids}
    common = sorted(set.intersection(*valid.values())) if ids else []
    res, x, data = [], [], []
    for vid in ids:
        lines = common if a.common_lines_only else sorted(valid[vid])
        tot = sum(_price(ctx.norm.get(vid, l), a.cost_basis) * ctx.line(l)["quantity"] for l in lines)
        res.append({"vendor_id": vid, "vendor": ctx.names[vid], "lines_compared": len(lines), "total": _r(tot),
                    "quality_status": _elig(ctx, vid)})
        x.append(ctx.names[vid]); data.append(_r(tot, 0))
    res.sort(key=lambda r: r["total"])
    cheapest = res[0] if res else None
    for r in res:
        r["delta_vs_cheapest"] = _r(r["total"] - cheapest["total"]) if cheapest else None
        r["delta_pct"] = _r(100 * (r["total"] - cheapest["total"]) / cheapest["total"], 2) if cheapest and cheapest["total"] else None
    title = (f"Total on {len(common)} lines all selected vendors quoted" if a.common_lines_only
             else "Total on each vendor's own comparable lines (NOT like-for-like)")
    return {"result": {"cost_basis": a.cost_basis, "common_lines_only": a.common_lines_only, "common_line_ids": common,
                       "vendors": res, "cheapest": cheapest["vendor_id"] if cheapest else None,
                       "warning": None if a.common_lines_only else "Different line sets; totals are not comparable."},
            "displays": [chart(title + f" ({a.cost_basis}, ₹ ex-GST)", "bar", x, [{"name": "Total ₹", "data": data}], "₹")]}


def _scenario_result(ctx, s):
    alloc = [[a.line_id, a.vendor_id, a.unit_price, a.value] + (["verify"] if a.review_required else []) for a in s.allocations]
    return {"scenario_id": s.scenario_id, "name": s.name, "strategy": s.strategy, "cost_basis": s.cost_basis_label,
            "solver": s.solver, "gross_total": s.gross_total, "conditional_discounts": s.discounts_applied,
            "net_total": s.net_total, "lines_allocated": s.lines_allocated, "lines_unallocated": s.lines_unallocated,
            "unallocated": s.unallocated, "vendor_shares": s.vendor_shares, "eligible_vendors": s.eligible_vendors,
            "excluded_vendors": s.excluded_vendors, "target_total_on_allocated_lines": s.target_total_allocated,
            "assumptions": s.assumptions, "risks": s.risks, "single_vendor_candidates": s.candidates,
            "allocations_[line,vendor,unit_price,value]": alloc}


def optimize_split_award(ctx: AnalysisContext, a: OptimizeArgs):
    p = AwardParams(strategy=a.strategy, cost_basis=a.cost_basis, eligible_only=a.eligible_only,
                    include_pending=a.include_pending,
                    include_vendor_ids=[_vid(ctx, v) for v in a.include_vendor_ids],
                    exclude_vendor_ids=[_vid(ctx, v) for v in a.exclude_vendor_ids],
                    exclude_unverified=a.exclude_unverified, max_vendors=a.max_vendors, max_share_pct=a.max_share_pct,
                    single_vendor_id=_vid(ctx, a.single_vendor_id) if a.single_vendor_id else None,
                    discount_aware=a.discount_aware, **({"weights": a.weights} if a.weights else {}))
    meta = {v["vendor_id"]: v for v in ctx.vendors}
    s = build_scenario(ctx.norm, ctx.eligibility, ctx.lines, meta, p, ctx.rfx.get("required_delivery_days", 15))
    ctx.scenarios[s.scenario_id] = s
    if ctx.on_scenario:
        ctx.on_scenario(s)
    rows = [[a_.line_id, a_.line_name, a_.vendor_name, f"{a_.quantity:,.0f}", a_.unit_price, _r(a_.value, 0),
             (ctx.names.get(a_.runner_up_vendor_id) or "—"), a_.runner_up_unit_price, "⚠ verify" if a_.review_required else ""]
            for a_ in s.allocations]
    rows += [[u["line_id"], u["line_name"], "UNALLOCATED", f"{u['quantity']:,}", None, None, "—", None, u["reason"][:80]]
             for u in s.unallocated]
    disp = [table(f"{s.name} — allocation ({s.cost_basis_label})",
                  ["Line", "Item", "Awarded to", "Qty", "Unit ₹", "Value ₹", "Runner-up", "Runner-up ₹", "Flag"], rows,
                  f"Gross ₹{s.gross_total:,.0f}; conditional discounts earned ₹{s.gross_total - s.net_total:,.0f}; net ₹{s.net_total:,.0f}"),
            chart(f"{s.name} — share of awarded value", "pie", [v["vendor_name"] for v in s.vendor_shares],
                  [{"name": "₹", "data": [v["value"] for v in s.vendor_shares]}])]
    return {"result": _scenario_result(ctx, s), "displays": disp}


def calculate_savings(ctx: AnalysisContext, a: SavingsArgs):
    s = ctx.scenarios.get(a.scenario_id)
    if not s:
        raise ToolError(f"Unknown scenario {a.scenario_id}; run optimize_split_award first. Known: {list(ctx.scenarios)}")
    if a.baseline == "target_price":
        sav = s.target_total_allocated - s.net_total
        return {"result": {"scenario": s.name, "baseline": "Target (last-contract) prices on allocated lines",
                           "target_total": s.target_total_allocated, "scenario_net": s.net_total, "savings": _r(sav),
                           "savings_pct": _r(100 * sav / s.target_total_allocated, 2) if s.target_total_allocated else None},
                "displays": []}
    if a.baseline == "best_single_vendor":
        meta = {v["vendor_id"]: v for v in ctx.vendors}
        bp = s.params.model_copy(update={"strategy": "SINGLE_VENDOR", "single_vendor_id": None, "max_vendors": None,
                                         "max_share_pct": None, "name": None})
        b = build_scenario(ctx.norm, ctx.eligibility, ctx.lines, meta, bp, ctx.rfx.get("required_delivery_days", 15))
        ctx.scenarios[b.scenario_id] = b
    else:
        b = ctx.scenarios.get(a.baseline)
        if not b:
            raise ToolError(f"Unknown baseline scenario {a.baseline}")
    cmp = compare_savings(s, b)
    cmp.update({"scenario_id": s.scenario_id, "baseline_scenario_id": b.scenario_id,
                "baseline_vendor": b.vendor_shares[0]["vendor_name"] if b.strategy == "SINGLE_VENDOR" and b.vendor_shares else None,
                "baseline_unallocated": b.unallocated})
    return {"result": cmp, "displays": [chart("Like-for-like cost on common lines", "bar", [b.name, s.name],
                                              [{"name": "₹ net", "data": [cmp["baseline_value_common"], cmp["scenario_value_common"]]}], "₹")]}


def generate_comparison_table(ctx: AnalysisContext, a: ComparisonTableArgs):
    lids = [x.upper() for x in a.line_ids] or [l["line_id"] for l in ctx.lines]
    vids = [_vid(ctx, v) for v in a.vendor_ids] or [v["vendor_id"] for v in ctx.vendors]
    rows = []
    for lid in lids:
        l = ctx.line(lid)
        r = [lid, l["name"]]
        for vid in vids:
            q = ctx.norm.get(vid, lid)
            if a.value == "original":
                r.append(f"{q.original_price:g} {q.original_currency} {q.price_basis_text or ''}".strip() if q and q.original_price is not None
                         else (q.status.replace('_', ' ').title() if q else "—"))
            else:
                v = {"unit_price": q.unit_price_base, "landed_unit_price": q.landed_unit_price,
                     "line_value": q.line_value_base}[a.value] if q and q.comparable else None
                r.append(_r(v, 2) if v is not None else (q.status.replace("_", " ").title() if q else "—"))
        rows.append(r)
    return {"result": {"rows": len(rows), "columns": len(vids) + 2, "shown_to_user": True},
            "displays": [table(a.title or f"Comparison — {a.value.replace('_', ' ')}", ["Line", "Item"] + [ctx.names[v] for v in vids], rows)]}


def generate_chart_data(ctx: AnalysisContext, a: ChartArgs):
    names = ctx.names
    if a.chart == "coverage":
        x = [v.vendor_name for v in ctx.norm.vendors]
        statuses = ["QUOTED", "NOT_COMPARABLE", "UNREADABLE", "NEEDS_CLARIFICATION", "NOT_QUOTED"]
        series = [{"name": s.replace("_", " ").title(), "data": [v.coverage_counts.get(s, 0) for v in ctx.norm.vendors]} for s in statuses]
        d = chart("Quotation coverage by vendor (lines)", "stacked_bar", x, series, "lines")
        return {"result": {"x": x, "series": series}, "displays": [d]}
    if a.chart == "quality_scores":
        x = [names[v["vendor_id"]] for v in ctx.vendors]
        data = [ctx.eligibility[v["vendor_id"]].quality_score if v["vendor_id"] in ctx.eligibility else None for v in ctx.vendors]
        return {"result": {"x": x, "data": data}, "displays": [chart("Questionnaire score (% passed)", "bar", x, [{"name": "score", "data": data}], "%")]}
    if a.chart == "price_spread":
        lids = [x.upper() for x in a.line_ids] or [l["line_id"] for l in ctx.lines]
        series = []
        for v in ctx.vendors:
            series.append({"name": v["name"], "data": [
                _r(_price(ctx.norm.get(v["vendor_id"], lid), a.cost_basis), 2) if ctx.norm.get(v["vendor_id"], lid).comparable else None
                for lid in lids]})
        return {"result": {"x": lids, "series": series},
                "displays": [chart("Unit price by line and vendor (₹, ex-GST)", "grouped_bar", lids, series, "₹ per unit")]}
    if a.chart == "vendor_totals_common_lines":
        return compare_vendor_costs(ctx, CompareVendorArgs(cost_basis=a.cost_basis))
    scs = [ctx.scenarios[s] for s in a.scenario_ids if s in ctx.scenarios] or list(ctx.scenarios.values())
    if not scs:
        raise ToolError("No scenarios yet; call optimize_split_award first")
    if a.chart == "scenario_shares":
        s = scs[-1]
        return {"result": {"scenario": s.name, "shares": s.vendor_shares},
                "displays": [chart(f"{s.name} — vendor share", "pie", [v["vendor_name"] for v in s.vendor_shares],
                                   [{"name": "₹", "data": [v["value"] for v in s.vendor_shares]}])]}
    x = [s.name for s in scs]
    series = [{"name": "Net total ₹", "data": [s.net_total for s in scs]},
              {"name": "Lines allocated", "data": [s.lines_allocated for s in scs]}]
    return {"result": {"scenarios": [{"id": s.scenario_id, "name": s.name, "net": s.net_total, "allocated": s.lines_allocated,
                                      "unallocated": s.lines_unallocated, "vendors": s.vendors_used} for s in scs]},
            "displays": [chart("Scenario comparison — net total (₹)", "bar", x, series[:1], "₹",
                               "Only compare totals between scenarios that allocate the same lines.")]}


def create_export_report(ctx: AnalysisContext, a: ExportArgs):
    if a.kind == "award_pdf" and not a.scenario_id:
        raise ToolError("award_pdf needs a scenario_id")
    if a.scenario_id and a.scenario_id not in ctx.scenarios:
        raise ToolError(f"Unknown scenario {a.scenario_id}")
    if not ctx.exporter:
        raise ToolError("Export service not available in this context")
    info = ctx.exporter(a.kind, {"scenario_id": a.scenario_id})
    return {"result": info, "displays": [{"type": "file", "title": info.get("filename"), "url": info.get("download_url")}]}


def draft_vendor_clarification(ctx: AnalysisContext, a: ClarifyArgs):
    vid = _vid(ctx, a.vendor_id)
    pts = []
    vs = next(v for v in ctx.norm.vendors if v.vendor_id == vid)
    for q in ctx.norm.quotes:
        if q.vendor_id != vid:
            continue
        if q.status in ("NEEDS_CLARIFICATION", "NOT_COMPARABLE", "UNREADABLE"):
            pts.append({"line_id": q.rfx_line_id, "item": ctx.line(q.rfx_line_id)["name"], "issue": q.status, "detail": q.reason})
        elif q.conversion_kind == "DERIVED_WEIGHT":
            pts.append({"line_id": q.rfx_line_id, "item": ctx.line(q.rfx_line_id)["name"], "issue": "CONFIRM_PER_PIECE_PRICE",
                        "detail": f"Quoted per kg; we estimate {q.trace[1].value * 1000:.0f} g/unit — please confirm price per piece"})
        elif q.review_required:
            pts.append({"line_id": q.rfx_line_id, "item": ctx.line(q.rfx_line_id)["name"], "issue": "CONFIRM_VALUE",
                        "detail": "; ".join(q.review_reasons)})
    if vs.freight_basis in ("EXTRA_AT_ACTUALS", "UNSPECIFIED"):
        pts.append({"issue": "FREIGHT", "detail": "Please quote freight to Chakan as a fixed amount per load or per unit"})
    if vs.tax_basis == "UNSPECIFIED":
        pts.append({"issue": "TAX", "detail": "Please confirm whether prices are inclusive or exclusive of GST and the rate"})
    return {"result": {"vendor": ctx.names[vid], "contact": next(v for v in ctx.vendors if v["vendor_id"] == vid).get("email"),
                       "rfx": ctx.rfx.get("reference"), "points": pts,
                       "instruction": "Draft a short, polite email listing these points; do not send it."}, "displays": []}


# ------------------------------------------------------------------ registry
TOOLS: dict[str, tuple[Callable, type[BaseModel], str]] = {
    "get_rfx_summary": (get_rfx_summary, NoArgs, "RFx header, line count, vendors, extraction status, normalization policy and FX assumptions."),
    "get_vendor_summary": (get_vendor_summary, VendorFilter, "Per-vendor coverage, totals on own lines, quality status, terms, freight, discounts."),
    "get_line_item_comparison": (get_line_item_comparison, LineComparisonArgs, "Per-line normalized unit prices for every vendor, statuses, and lowest (optionally eligible-only) vendor."),
    "get_vendor_quotation_details": (get_vendor_quotation_details, VendorDetailArgs, "One vendor's lines: original quote, conversion, normalized price, confidence, evidence, optional calculation trace."),
    "get_quality_eligibility": (get_quality_eligibility, OneVendorOpt, "Questionnaire evaluation and eligibility per vendor with reasons."),
    "get_missing_quotations": (get_missing_quotations, OneVendorOpt, "Coverage gaps: not quoted, needs clarification, not comparable, unreadable."),
    "get_extraction_exceptions": (get_extraction_exceptions, ExceptionArgs, "Values needing human verification or clarification, with source locations."),
    "calculate_normalized_cost": (calculate_normalized_cost, NormCostArgs, "Recompute one vendor-line normalized cost with full trace; optional what-if FX/pack/freight overrides (not persisted)."),
    "compare_vendor_costs": (compare_vendor_costs, CompareVendorArgs, "Compare vendor totals like-for-like on common lines (default) or own lines."),
    "optimize_split_award": (optimize_split_award, OptimizeArgs, "Build an award scenario (single vendor, lowest-price split, balanced) with eligibility, constraints, discount-aware search. Returns scenario_id."),
    "calculate_savings": (calculate_savings, SavingsArgs, "Savings of a scenario vs best single vendor, target prices, or another scenario (like-for-like lines)."),
    "generate_comparison_table": (generate_comparison_table, ComparisonTableArgs, "Show the user a comparison table (unit/landed/line value/original quote)."),
    "generate_chart_data": (generate_chart_data, ChartArgs, "Show the user a chart: coverage, price spread, quality scores, vendor totals, scenario comparison/shares."),
    "create_export_report": (create_export_report, ExportArgs, "Create a downloadable export (comparison XLSX, award PDF, exceptions XLSX, quality PDF, audit CSV)."),
    "draft_vendor_clarification": (draft_vendor_clarification, ClarifyArgs, "List the points a vendor must clarify (unresolved references, pack sizes, freight, per-kg pricing)."),
}


def tool_specs() -> list[dict]:
    return [{"name": n, "description": d, "input_schema": inline_schema(m.model_json_schema())} for n, (_, m, d) in TOOLS.items()]


def run_tool(ctx: AnalysisContext, name: str, args: dict) -> dict:
    if name not in TOOLS:
        raise ToolError(f"Unknown tool {name}")
    fn, model, _ = TOOLS[name]
    parsed = model.model_validate(args or {})
    return fn(ctx, parsed)
