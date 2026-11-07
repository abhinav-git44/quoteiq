"""Deterministic award scenarios.

SINGLE_VENDOR       one eligible vendor takes every line it validly quoted; the rest are UNALLOCATED.
LOWEST_PRICE_SPLIT  cheapest eligible, comparable quote per line (optionally ≤K vendors / share cap → MILP).
BALANCED            minimise risk-adjusted cost = price × (1 + Σ wᵢ·(1 − scoreᵢ)), with a concentration cap.

Never allocates a line no eligible vendor validly quoted. Conditional discounts are applied
only when the scenario actually satisfies their condition.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Optional

import numpy as np
from pydantic import BaseModel, Field

from app.domain.normalized import NormalizationResult, NormalizedQuote

Strategy = Literal["SINGLE_VENDOR", "LOWEST_PRICE_SPLIT", "BALANCED"]


class AwardParams(BaseModel):
    strategy: Strategy = "LOWEST_PRICE_SPLIT"
    cost_basis: Literal["base", "landed"] = "base"
    eligible_only: bool = True
    include_pending: bool = False
    include_vendor_ids: list[str] = Field(default_factory=list)
    exclude_vendor_ids: list[str] = Field(default_factory=list)
    exclude_unverified: bool = False
    max_vendors: Optional[int] = None
    max_share_pct: Optional[float] = None
    single_vendor_id: Optional[str] = None
    discount_aware: bool = True
    weights: dict[str, float] = Field(default_factory=lambda: {"quality": 0.15, "delivery": 0.10, "history": 0.10})
    name: Optional[str] = None


class Allocation(BaseModel):
    line_id: str
    line_name: str
    vendor_id: str
    vendor_name: str
    quantity: float
    uom: str
    unit_price: float
    value: float
    review_required: bool
    confidence: float
    options_count: int
    runner_up_vendor_id: Optional[str] = None
    runner_up_unit_price: Optional[float] = None
    target_unit_price: Optional[float] = None


class Scenario(BaseModel):
    scenario_id: str
    name: str
    strategy: Strategy
    params: AwardParams
    cost_basis_label: str
    allocations: list[Allocation]
    unallocated: list[dict[str, Any]]
    vendor_shares: list[dict[str, Any]]
    gross_total: float
    discounts_applied: list[dict[str, Any]]
    net_total: float
    target_total_allocated: float
    lines_allocated: int
    lines_unallocated: int
    vendors_used: int
    eligible_vendors: list[str]
    excluded_vendors: list[dict[str, str]]
    assumptions: list[str]
    risks: list[str]
    candidates: list[dict[str, Any]] = Field(default_factory=list)   # single-vendor comparison
    solver: str = "greedy"


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _price(q: NormalizedQuote, basis: str) -> Optional[float]:
    return q.landed_unit_price if basis == "landed" else q.unit_price_base


def _sid(params: AwardParams) -> str:
    return "SCN-" + hashlib.sha1(json.dumps(params.model_dump(), sort_keys=True).encode()).hexdigest()[:8].upper()


def _vendor_pool(norm: NormalizationResult, eligibility: dict[str, Any], p: AwardParams) -> tuple[list[str], list[dict]]:
    pool, excluded = [], []
    for v in norm.vendors:
        el = eligibility.get(v.vendor_id)
        st = _get(el, "status", "PENDING")
        if p.include_vendor_ids and v.vendor_id not in p.include_vendor_ids:
            excluded.append({"vendor_id": v.vendor_id, "reason": "Not in requested vendor set"}); continue
        if v.vendor_id in p.exclude_vendor_ids:
            excluded.append({"vendor_id": v.vendor_id, "reason": "Excluded by request"}); continue
        if p.eligible_only and st != "ELIGIBLE" and not (p.include_pending and st == "PENDING"):
            reasons = _get(el, "reasons", ["No questionnaire evaluation"])
            excluded.append({"vendor_id": v.vendor_id, "reason": f"Quality {st}: " + "; ".join(reasons[:2])}); continue
        pool.append(v.vendor_id)
    return pool, excluded


def _options(norm, rfx_lines, pool, p) -> dict[str, list[NormalizedQuote]]:
    opts: dict[str, list[NormalizedQuote]] = {}
    for l in rfx_lines:
        o = []
        for q in norm.quotes:
            if q.rfx_line_id != l["line_id"] or q.vendor_id not in pool or not q.comparable:
                continue
            if _price(q, p.cost_basis) is None:
                continue
            if p.exclude_unverified and q.review_required:
                continue
            o.append(q)
        opts[l["line_id"]] = sorted(o, key=lambda q: _price(q, p.cost_basis))
    return opts


def _non_price_penalty(vendor_id, norm, eligibility, vendor_meta, rfx_days, w) -> float:
    qs = _get(eligibility.get(vendor_id), "quality_score", 0) or 0
    vs = next((v for v in norm.vendors if v.vendor_id == vendor_id), None)
    dmax = (vs.delivery_days_max or vs.delivery_days_min) if vs else None
    dscore = 1.0 if not dmax else min(1.0, rfx_days / dmax)
    hist = (vendor_meta.get(vendor_id, {}).get("historical_score") or 70) / 100
    return w.get("quality", 0) * (1 - qs / 100) + w.get("delivery", 0) * (1 - dscore) + w.get("history", 0) * (1 - hist)


def _solve_milp(opts, cost_fn, K, share, pool, forced: Optional[dict[str, str]] = None) -> Optional[dict[str, str]]:
    from scipy.optimize import LinearConstraint, Bounds, milp

    pairs = [(lid, q.vendor_id, q) for lid, os_ in opts.items() for q in os_]
    if not pairs:
        return {}
    vendors = sorted({v for _, v, _ in pairs})
    nx, ny = len(pairs), len(vendors)
    n = nx + ny
    c = np.zeros(n)
    for i, (_, _, q) in enumerate(pairs):
        c[i] = cost_fn(q)
    A, lb, ub = [], [], []
    for lid in {l for l, _, _ in pairs}:
        row = np.zeros(n)
        for i, (l2, _, _) in enumerate(pairs):
            if l2 == lid:
                row[i] = 1
        A.append(row); lb.append(1); ub.append(1)
    for i, (_, v, _) in enumerate(pairs):     # x ≤ y
        row = np.zeros(n); row[i] = 1; row[nx + vendors.index(v)] = -1
        A.append(row); lb.append(-np.inf); ub.append(0)
    if K:
        row = np.zeros(n); row[nx:] = 1
        A.append(row); lb.append(0); ub.append(K)
    if share:
        s = share / 100
        for v in vendors:
            row = np.zeros(n)
            for i, (_, v2, q) in enumerate(pairs):
                val = q.line_value_base or 0
                row[i] = (1 - s) * val if v2 == v else -s * val
            A.append(row); lb.append(-np.inf); ub.append(0)
    lo = np.zeros(n)
    for i, (lid, v, _) in enumerate(pairs):
        if forced and forced.get(lid) == v:
            lo[i] = 1
    res = milp(c, constraints=LinearConstraint(np.array(A), lb, ub), integrality=np.ones(n),
               bounds=Bounds(lo, np.ones(n)), options={"time_limit": 20})
    if res.x is None:
        return None
    return {pairs[i][0]: pairs[i][1] for i in range(nx) if res.x[i] > 0.5}


def build_scenario(norm: NormalizationResult, eligibility: dict[str, Any], rfx_lines: list[dict],
                   vendor_meta: dict[str, dict], params: AwardParams, rfx_required_days: int = 15) -> Scenario:
    p = params
    pool, excluded = _vendor_pool(norm, eligibility, p)
    opts = _options(norm, rfx_lines, pool, p)
    names = {v.vendor_id: v.vendor_name for v in norm.vendors}
    by_line = {l["line_id"]: l for l in rfx_lines}
    assumptions = [f"Cost basis: {'landed (base + freight)' if p.cost_basis == 'landed' else 'base price'}, "
                   f"{norm.base_currency} ex-GST per RFx unit"]
    risks: list[str] = []
    solver = "greedy"
    choice: dict[str, str] = {}
    candidates: list[dict] = []

    if p.strategy == "SINGLE_VENDOR":
        for v in pool:
            cov = [lid for lid, os_ in opts.items() if any(q.vendor_id == v for q in os_)]
            tot = sum(_price(next(q for q in opts[lid] if q.vendor_id == v), p.cost_basis) * by_line[lid]["quantity"] for lid in cov)
            candidates.append({"vendor_id": v, "vendor_name": names[v], "lines_covered": len(cov), "total_covered": round(tot, 2)})
        candidates.sort(key=lambda c: (-c["lines_covered"], c["total_covered"]))
        pick = p.single_vendor_id if p.single_vendor_id in pool else (candidates[0]["vendor_id"] if candidates else None)
        if p.single_vendor_id and p.single_vendor_id not in pool:
            risks.append(f"Requested vendor {p.single_vendor_id} is not in the eligible pool; picked best available instead")
        if pick:
            for lid, os_ in opts.items():
                if any(q.vendor_id == pick for q in os_):
                    choice[lid] = pick
            assumptions.append("Single vendor chosen by most comparable lines covered, then lowest total on those lines")
    elif p.strategy == "LOWEST_PRICE_SPLIT":
        def solve(forced):
            if p.max_vendors or p.max_share_pct:
                return _solve_milp(opts, lambda q: _price(q, p.cost_basis) * q.quantity, p.max_vendors, p.max_share_pct, pool, forced)
            return {lid: (forced.get(lid) or os_[0].vendor_id) for lid, os_ in opts.items() if os_}
        solver = "MILP (scipy/HiGHS)" if (p.max_vendors or p.max_share_pct) else "greedy"
    else:  # BALANCED
        pen = {v: _non_price_penalty(v, norm, eligibility, vendor_meta, rfx_required_days, p.weights) for v in pool}
        share = p.max_share_pct if p.max_share_pct is not None else 60.0
        cost = lambda q: _price(q, p.cost_basis) * q.quantity * (1 + pen[q.vendor_id])  # noqa: E731

        def solve(forced):
            sol = _solve_milp(opts, cost, p.max_vendors, share, pool, forced)
            if sol is None and not forced:
                risks.append(f"Share cap {share}% infeasible with available bids — cap relaxed")
                sol = _solve_milp(opts, cost, p.max_vendors, None, pool)
            return sol
        solver = "MILP (scipy/HiGHS)"
        assumptions.append("Risk-adjusted cost = price × (1 + " + " + ".join(f"{w}·(1−{k} score)" for k, w in p.weights.items()) +
                           f"); concentration cap {share}% of awarded value")
        assumptions.append("Vendor penalties: " + ", ".join(f"{names[v]} +{pen[v] * 100:.1f}%" for v in pool))

    def materialize(choice: dict[str, str]):
        allocations, unallocated = [], []
        for l in rfx_lines:
            lid = l["line_id"]
            os_ = opts.get(lid, [])
            v = choice.get(lid)
            if not v:
                if not os_:
                    why = []
                    for q in norm.quotes:
                        if q.rfx_line_id == lid and q.vendor_id in pool:
                            why.append(f"{names[q.vendor_id]}: {q.status.replace('_', ' ').lower()}"
                                       + (f" ({q.reason})" if q.reason and q.status != "NOT_QUOTED" else ""))
                    reason = "No eligible vendor with a valid, comparable quote" + (" — " + "; ".join(why) if why else "")
                else:
                    reason = "Not covered by the selected vendor"
                unallocated.append({"line_id": lid, "line_name": l["name"], "quantity": l["quantity"], "reason": reason,
                                    "options_count": len(os_)})
                continue
            q = next(q for q in os_ if q.vendor_id == v)
            up = _price(q, p.cost_basis)
            others = [o for o in os_ if o.vendor_id != v]
            allocations.append(Allocation(
                line_id=lid, line_name=l["name"], vendor_id=v, vendor_name=names[v], quantity=l["quantity"], uom=l["uom"],
                unit_price=round(up, 4), value=round(up * l["quantity"], 2), review_required=q.review_required,
                confidence=q.confidence, options_count=len(os_),
                runner_up_vendor_id=others[0].vendor_id if others else None,
                runner_up_unit_price=round(_price(others[0], p.cost_basis), 4) if others else None,
                target_unit_price=l.get("target_price_inr")))
        gross = round(sum(a.value for a in allocations), 2)
        discounts = []
        for vs in norm.vendors:
            awarded = [a for a in allocations if a.vendor_id == vs.vendor_id]
            if not awarded:
                continue
            quoted_comparable = {q.rfx_line_id for q in norm.quotes if q.vendor_id == vs.vendor_id and q.comparable}
            base_val = sum((norm.get(vs.vendor_id, a.line_id).unit_price_base or 0) * a.quantity for a in awarded)
            for d in vs.conditional_discounts:
                ct, applied, why = d.get("condition_type"), False, ""
                if d.get("kind") != "PERCENT" or d.get("already_included_in_prices"):
                    continue
                if ct == "ALL_QUOTED_ITEMS_AWARDED":
                    applied = quoted_comparable <= {a.line_id for a in awarded}
                    why = "all quoted items awarded" if applied else f"only {len(awarded)}/{len(quoted_comparable)} quoted items awarded"
                elif ct == "MIN_ORDER_VALUE" and d.get("condition_value"):
                    applied = base_val >= d["condition_value"]
                    why = f"awarded value {base_val:,.0f} vs minimum {d['condition_value']:,.0f}"
                elif ct == "EARLY_PAYMENT":
                    why = "early-payment discount excluded by policy (treasury decision)"
                else:
                    why = "condition not evaluable automatically"
                amt = round(base_val * d["value"] / 100, 2) if applied else 0.0
                discounts.append({"vendor_id": vs.vendor_id, "vendor_name": vs.vendor_name, "pct": d["value"],
                                  "condition": d.get("condition_text") or ct, "applied": applied, "amount": amt, "why": why})
        net = round(gross - sum(d["amount"] for d in discounts), 2)
        return allocations, unallocated, gross, discounts, net

    if p.strategy == "SINGLE_VENDOR":
        allocations, unallocated, gross, discounts, net = materialize(choice)
        for c in candidates:
            _, _, _, _, c_net = materialize({lid: c["vendor_id"] for lid, os_ in opts.items() if any(q.vendor_id == c["vendor_id"] for q in os_)})
            c["net_after_conditional_discounts"] = c_net
    else:
        # Discount-aware search: try award patterns that earn "all quoted items" discounts.
        disc_vendors = [v for v in pool if any(d.get("condition_type") == "ALL_QUOTED_ITEMS_AWARDED" and d.get("kind") == "PERCENT"
                                               and not d.get("already_included_in_prices")
                                               for d in next(x for x in norm.vendors if x.vendor_id == v).conditional_discounts)][:4]
        if not p.discount_aware:
            disc_vendors = []
        from itertools import combinations
        best, tried, plain_net = None, 0, None
        for r in range(len(disc_vendors) + 1):
            for subset in combinations(disc_vendors, r):
                forced, ok = {}, True
                for v in subset:
                    need = {q.rfx_line_id for q in norm.quotes if q.vendor_id == v and q.comparable}
                    avail = {lid for lid, os_ in opts.items() if any(q.vendor_id == v for q in os_)}
                    if not need <= avail:
                        ok = False; break
                    for lid in need:
                        if lid in forced:
                            ok = False; break
                        forced[lid] = v
                if not ok:
                    continue
                ch = solve(forced)
                tried += 1
                if ch is None:
                    continue
                m = materialize(ch)
                if not subset:
                    plain_net = m[4]
                key = m[4] if p.strategy == "LOWEST_PRICE_SPLIT" else (
                    sum(a.value * (1 + pen[a.vendor_id]) for a in m[0]) - sum(d["amount"] for d in m[3]))
                if best is None or key < best[0] - 0.5:
                    best = (key, subset, m)
        if best is None:
            allocations, unallocated, gross, discounts, net = materialize({})
        else:
            _, subset, (allocations, unallocated, gross, discounts, net) = best
            if disc_vendors:
                assumptions.append(f"Discount-aware: evaluated {tried} award pattern(s) including 'all quoted items' discounts from "
                                   + ", ".join(names[v] for v in disc_vendors) + "; "
                                   + (f"best pattern awards {', '.join(names[v] for v in subset)} all its quoted lines"
                                      if subset else "best pattern is plain lowest price per line"))
                if subset and plain_net is not None:
                    assumptions.append(f"Plain lowest-price-per-line would net {norm.base_currency} {plain_net:,.0f} "
                                       f"(forfeits the conditional discount); this pattern nets {net:,.0f}")

    shares = []
    for v in sorted({a.vendor_id for a in allocations}):
        val = sum(a.value for a in allocations if a.vendor_id == v)
        shares.append({"vendor_id": v, "vendor_name": names[v], "lines": sum(1 for a in allocations if a.vendor_id == v),
                       "value": round(val, 2), "pct": round(100 * val / gross, 1) if gross else 0})
    shares.sort(key=lambda s: -s["value"])

    single = [a.line_id for a in allocations if a.options_count == 1]
    if single:
        risks.append(f"{len(single)} line(s) have only one eligible comparable bid (single-source risk): {', '.join(single)}")
    unver = [a.line_id for a in allocations if a.review_required]
    if unver:
        risks.append(f"{len(unver)} allocated line(s) rest on values still awaiting human verification: {', '.join(unver)}")
    if shares and shares[0]["pct"] > 60:
        risks.append(f"Concentration: {shares[0]['vendor_name']} holds {shares[0]['pct']}% of awarded value")
    if unallocated:
        risks.append(f"{len(unallocated)} line(s) UNALLOCATED — need re-quote, clarification or a pending vendor")
    for vid in {a.vendor_id for a in allocations}:
        vs = next(v for v in norm.vendors if v.vendor_id == vid)
        if vs.fx and vs.fx.rate_type != "IDENTITY":
            assumptions.append(f"{vs.vendor_name} quoted in {vs.currency}; converted at {vs.fx.rate} ({vs.fx.source})")
        if p.cost_basis == "landed" and vs.freight_basis in ("EXTRA_AT_ACTUALS", "UNSPECIFIED"):
            assumptions.append(f"{vs.vendor_name} freight not quantified; assumed {norm.policy['freight_at_actuals_assumed_pct']}%")
        if p.cost_basis == "base" and vs.freight_basis not in ("INCLUDED",):
            assumptions.append(f"{vs.vendor_name} freight is extra ({vs.freight_basis.replace('_', ' ').lower()}) and NOT in base-price totals")

    target = sum((a.target_unit_price or 0) * a.quantity for a in allocations)
    nm = p.name or {"SINGLE_VENDOR": "Single vendor", "LOWEST_PRICE_SPLIT": "Lowest-price split" + ("" if p.discount_aware else " (per-line, no discount search)"),
                    "BALANCED": "Balanced"}[p.strategy] + (f" (≤{p.max_vendors} vendors)" if p.max_vendors else "") + \
        (" · landed" if p.cost_basis == "landed" else "")
    return Scenario(scenario_id=_sid(p), name=nm, strategy=p.strategy, params=p,
                    cost_basis_label="Landed (base + freight), ex-GST" if p.cost_basis == "landed" else "Base price, ex-GST",
                    allocations=allocations, unallocated=unallocated, vendor_shares=shares, gross_total=gross,
                    discounts_applied=discounts, net_total=net, target_total_allocated=round(target, 2),
                    lines_allocated=len(allocations), lines_unallocated=len(unallocated), vendors_used=len(shares),
                    eligible_vendors=pool, excluded_vendors=excluded, assumptions=list(dict.fromkeys(assumptions)),
                    risks=risks, candidates=candidates, solver=solver)


def compare_savings(scenario: Scenario, baseline: Scenario) -> dict[str, Any]:
    """Like-for-like: only lines allocated in BOTH scenarios are compared."""
    a = {x.line_id: x for x in scenario.allocations}
    b = {x.line_id: x for x in baseline.allocations}
    common = sorted(set(a) & set(b))
    sv = sum(a[l].value for l in common)
    bv = sum(b[l].value for l in common)

    def disc_share(s: Scenario, lines):
        tot = 0.0
        for d in s.discounts_applied:
            if d["applied"]:
                vlines = [x for x in s.allocations if x.vendor_id == d["vendor_id"]]
                vv = sum(x.value for x in vlines) or 1
                tot += d["amount"] * sum(x.value for x in vlines if x.line_id in lines) / vv
        return tot
    sv_net, bv_net = sv - disc_share(scenario, common), bv - disc_share(baseline, common)
    return {
        "scenario": scenario.name, "baseline": baseline.name, "common_lines": len(common),
        "scenario_only_lines": sorted(set(a) - set(b)), "baseline_only_lines": sorted(set(b) - set(a)),
        "scenario_value_common": round(sv_net, 2), "baseline_value_common": round(bv_net, 2),
        "savings": round(bv_net - sv_net, 2), "savings_pct": round(100 * (bv_net - sv_net) / bv_net, 2) if bv_net else None,
        "note": "Compared on lines allocated in both scenarios only, net of conditional discounts that each scenario earns.",
    }
