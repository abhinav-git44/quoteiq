from app.demo.catalog import QUESTIONNAIRE, QUESTIONNAIRE_ANSWERS, RFX, VENDORS
from app.optimization.award import AwardParams, build_scenario, compare_savings
from app.quality.eligibility import evaluate_vendor

META = {v["vendor_id"]: v for v in VENDORS}


def ev(until, conf=100, status="SUCCEEDED"):
    return {"iso9001_certificate": {"status": status, "valid_until": until, "confidence": conf}}


def test_expired_certificate_fails_despite_yes():
    e = evaluate_vendor("V-C", QUESTIONNAIRE, QUESTIONNAIRE_ANSWERS["V-C"], ev("2026-03-31"), RFX["issue_date"])
    assert e.status == "INELIGIBLE" and "expired" in e.reasons[0]


def test_missing_mandatory_answer_stays_pending():
    e = evaluate_vendor("V-D", QUESTIONNAIRE, QUESTIONNAIRE_ANSWERS["V-D"], ev("2027-09-09"), RFX["issue_date"])
    assert e.status == "PENDING" and any("Q06" in r for r in e.reasons)


def test_unverified_evidence_never_auto_passes():
    e = evaluate_vendor("V-A", QUESTIONNAIRE, QUESTIONNAIRE_ANSWERS["V-A"], ev(None, status="AI_UNAVAILABLE"), RFX["issue_date"])
    assert e.status == "PENDING"
    e = evaluate_vendor("V-A", QUESTIONNAIRE, QUESTIONNAIRE_ANSWERS["V-A"], {}, RFX["issue_date"])
    assert e.status == "PENDING"
    e = evaluate_vendor("V-A", QUESTIONNAIRE, QUESTIONNAIRE_ANSWERS["V-A"], ev("2027-05-31", conf=40), RFX["issue_date"])
    assert e.status == "PENDING"


def test_numeric_rules_and_reviewer_override():
    ans = dict(QUESTIONNAIRE_ANSWERS["V-A"], Q05=20)
    e = evaluate_vendor("V-A", QUESTIONNAIRE, ans, ev("2027-05-31"), RFX["issue_date"])
    assert e.status == "INELIGIBLE"
    e = evaluate_vendor("V-D", QUESTIONNAIRE, QUESTIONNAIRE_ANSWERS["V-D"], ev("2027-09-09"), RFX["issue_date"],
                        overrides={"Q06": {"status": "PASS", "comment": "Confirmed by phone, batch nos. on bundles"}})
    assert e.status == "ELIGIBLE" and any(a.overridden for a in e.answers)


def test_demo_eligibility(ctx):
    st = {k: v.status for k, v in ctx.eligibility.items()}
    assert st == {"V-A": "ELIGIBLE", "V-B": "ELIGIBLE", "V-C": "INELIGIBLE", "V-D": "PENDING", "V-E": "ELIGIBLE"}


# ---------------------------------------------------------------- award
def sc(ctx, **kw):
    return build_scenario(ctx.norm, ctx.eligibility, ctx.lines, META, AwardParams(**kw))


def test_split_only_uses_eligible_and_never_allocates_invalid_quotes(ctx):
    s = sc(ctx)
    assert {a.vendor_id for a in s.allocations} <= {"V-A", "V-B", "V-E"}
    for a in s.allocations:
        assert ctx.norm.get(a.vendor_id, a.line_id).comparable
    assert {e["vendor_id"] for e in s.excluded_vendors} == {"V-C", "V-D"}


def test_unallocated_when_no_eligible_comparable_quote(ctx):
    s = sc(ctx, include_vendor_ids=["V-E"])
    assert s.lines_unallocated == 11 and all("clarification" in u["reason"] for u in s.unallocated)
    assert all(a.vendor_id == "V-E" for a in s.allocations)


def test_discount_aware_search_beats_naive_per_line(ctx):
    naive = sc(ctx, discount_aware=False)
    smart = sc(ctx)
    assert smart.net_total < naive.net_total
    assert any(d["applied"] and d["vendor_id"] == "V-B" for d in smart.discounts_applied)
    assert not any(d["applied"] for d in naive.discounts_applied)


def test_max_vendors_and_share_cap(ctx):
    s = sc(ctx, max_vendors=1)
    assert s.vendors_used == 1 and s.solver.startswith("MILP")
    s = sc(ctx, max_share_pct=50, discount_aware=False)
    assert all(v["pct"] <= 50.01 for v in s.vendor_shares)


def test_single_vendor_and_like_for_like_savings(ctx):
    single = sc(ctx, strategy="SINGLE_VENDOR")
    assert single.vendors_used == 1 and single.candidates[0]["lines_covered"] >= single.candidates[-1]["lines_covered"]
    split = sc(ctx)
    cmp = compare_savings(split, single)
    assert cmp["common_lines"] == min(split.lines_allocated, single.lines_allocated)
    assert cmp["savings"] == round(cmp["baseline_value_common"] - cmp["scenario_value_common"], 2)


def test_ineligible_cheapest_vendor_shows_cost_of_quality_rule(ctx):
    with_c = sc(ctx, eligible_only=False)
    assert any(v["vendor_id"] == "V-C" for v in with_c.vendor_shares)
    assert with_c.net_total < sc(ctx).net_total


def test_exclude_unverified_removes_flagged_values(ctx):
    s = sc(ctx, exclude_unverified=True)
    assert not any(a.review_required for a in s.allocations)


def test_balanced_respects_default_concentration_cap(ctx):
    s = sc(ctx, strategy="BALANCED")
    assert all(v["pct"] <= 60.01 for v in s.vendor_shares)
