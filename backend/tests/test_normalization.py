import pytest

from app.core.config import Settings
from app.demo.catalog import EXCHANGE_RATES, rfx_line_items
from app.domain.normalized import DiscountInput, QuoteLineInput, VendorQuoteInput
from app.normalization.engine import FxTable, normalize
from app.normalization.weight import estimate_weight
from sim_extraction import GT

FX = FxTable(EXCHANGE_RATES)
LINE = {"line_id": "X1", "name": "box", "quantity": 1000, "uom": "pcs",
        "spec": {"kind": "rsc", "length_mm": 400, "width_mm": 300, "height_mm": 300, "ply": 5, "board_gsm": 820}}
S = Settings(anthropic_api_key=None)


def vq(lines, cov=None, **kw):
    cov = cov or {l.rfx_line_id: "QUOTED" for l in lines}
    return VendorQuoteInput(vendor_id=kw.pop("vid", "V"), vendor_name="V", currency=kw.pop("currency", "INR"),
                            lines=lines, coverage=cov, **kw)


def q(price, uom="PIECE", **kw):
    return QuoteLineInput(rfx_line_id=kw.pop("lid", "X1"), price=price, currency=kw.pop("currency", None), price_uom=uom, **kw)


def test_spec_example_box_vs_100_vs_piece():
    """₹500/box of 10, ₹4,500 per 100, ₹48/pc -> 50, 45, 48 per piece."""
    r = normalize([LINE], [vq([q(500, "BOX", units_per_price_uom=10)], vid="A"), vq([q(4500, "HUNDRED")], vid="B"),
                           vq([q(48)], vid="C")], FX, S)
    assert [r.get(v, "X1").unit_price_base for v in "ABC"] == [50, 45, 48]


def test_box_without_pack_size_is_not_comparable_never_guessed():
    r = normalize([LINE], [vq([q(500, "BOX")])], FX, S)
    n = r.get("V", "X1")
    assert n.status == "NOT_COMPARABLE" and n.unit_price_base is None and "units per box" in n.reason


def test_missing_is_not_quoted_never_zero_and_coverage():
    l2 = dict(LINE, line_id="X2")
    r = normalize([LINE, l2], [vq([q(10)], cov={"X1": "QUOTED"})], FX, S)
    n = r.get("V", "X2")
    assert n.status == "NOT_QUOTED" and n.unit_price_base is None and n.line_value_base is None
    assert r.vendors[0].coverage_pct == 50.0


def test_usd_per_kg_uses_disclosed_weight_and_fx_and_requires_review():
    r = normalize([LINE], [vq([q(0.59, "KG")], currency="USD")], FX, S)
    n = r.get("V", "X1")
    w = estimate_weight(LINE["spec"]).weight_kg
    assert n.unit_price_base == pytest.approx(0.59 * w * 88.5, rel=1e-6)
    assert n.conversion_kind == "DERIVED_WEIGHT" and n.review_required
    assert any("assumed demo rate" in a for a in n.assumptions)
    accepted = normalize([LINE], [vq([q(0.59, "KG", accepted_assumptions=["DERIVED_WEIGHT"])], currency="USD")], FX, S)
    assert not accepted.get("V", "X1").review_required


def test_unknown_currency_blocks_comparison():
    r = normalize([LINE], [vq([q(10)], currency="JPY")], FX, S)
    assert r.get("V", "X1").status == "NOT_COMPARABLE"


def test_conditional_discount_not_applied_at_line_level_but_unconditional_is():
    d_cond = DiscountInput(kind="PERCENT", value=4, scope="ORDER", condition_type="ALL_QUOTED_ITEMS_AWARDED")
    d_unc = DiscountInput(kind="PERCENT", value=2, scope="ORDER", condition_type="NONE")
    r = normalize([LINE], [vq([q(100)], discounts=[d_cond])], FX, S)
    assert r.get("V", "X1").unit_price_base == 100 and r.vendors[0].conditional_discounts
    r = normalize([LINE], [vq([q(100)], discounts=[d_unc])], FX, S)
    assert r.get("V", "X1").unit_price_base == 98


def test_discount_already_in_price_is_not_double_counted():
    d = DiscountInput(kind="PERCENT", value=5, scope="ORDER", condition_type="NONE", already_included_in_prices=True)
    assert normalize([LINE], [vq([q(100)], discounts=[d])], FX, S).get("V", "X1").unit_price_base == 100


def test_early_payment_discount_follows_policy():
    d = DiscountInput(kind="PERCENT", value=2, scope="ORDER", condition_type="EARLY_PAYMENT")
    off = normalize([LINE], [vq([q(100)], discounts=[d])], FX, S).get("V", "X1").unit_price_base
    on = normalize([LINE], [vq([q(100)], discounts=[d])], FX, Settings(anthropic_api_key=None, apply_early_payment_discounts=True)).get("V", "X1").unit_price_base
    assert off == 100 and on == 98


def test_tax_inclusive_prices_are_backed_out():
    r = normalize([LINE], [vq([q(112)], tax_basis="INCLUDED", tax_rate_pct=12)], FX, S)
    assert r.get("V", "X1").unit_price_base == pytest.approx(100)


def test_freight_per_load_allocated_pro_rata_and_sums_to_total():
    l2 = dict(LINE, line_id="X2", quantity=3000)
    r = normalize([LINE, l2], [vq([q(10), q(20, lid="X2")], freight_basis="EXTRA_PER_LOAD", freight_amount=14000, freight_loads=4)], FX, S)
    alloc = sum(n.freight_per_unit * n.quantity for n in r.quotes)
    assert alloc == pytest.approx(56000)
    assert r.vendors[0].freight_total_base == 56000


def test_freight_per_unit_and_at_actuals_assumption():
    r = normalize([LINE], [vq([q(10)], freight_basis="EXTRA_PER_UNIT", freight_amount=2.5)], FX, S)
    assert r.get("V", "X1").landed_unit_price == 12.5
    r = normalize([LINE], [vq([q(10)], freight_basis="EXTRA_AT_ACTUALS")], FX, S)
    n = r.get("V", "X1")
    assert n.landed_unit_price == pytest.approx(10.4) and any("assumed" in a.lower() for a in n.assumptions)


def test_end_to_end_unit_prices_match_ground_truth(ctx):
    """Normalized prices from the real documents (via simulated model output) match the generator's truth."""
    checked = 0
    for vid, v in GT["vendors"].items():
        for lid, g in v["lines"].items():
            n = ctx.norm.get(vid, lid)
            if g["status"] == "QUOTED":
                assert n.status == "QUOTED", (vid, lid, n.status, n.reason)
                assert n.unit_price_base == pytest.approx(g["unit_price_inr_per_rfx_uom"], rel=2e-3), (vid, lid)
                checked += 1
            else:
                assert n.status == g["status"], (vid, lid, n.status)
    assert checked >= 120


def test_weight_model_is_none_for_items_without_geometry():
    edge = next(l for l in rfx_line_items() if l["line_id"] == "L17")
    assert estimate_weight(edge["spec"]) is None


def test_line_scope_unconditional_discount_is_not_double_counted_or_shown_as_conditional():
    d = DiscountInput(kind="PERCENT", value=3, scope="LINE", rfx_line_ids=["X1"], condition_type="NONE")
    # line already carries the 3% (vendor's Disc % column) -> not applied again, not listed as conditional
    r = normalize([LINE], [vq([q(100, line_discount_pct=3)], discounts=[d])], FX, S)
    assert r.get("V", "X1").unit_price_base == 97 and r.vendors[0].conditional_discounts == []
    # line without its own discount -> applied once
    r = normalize([LINE], [vq([q(100)], discounts=[d])], FX, S)
    assert r.get("V", "X1").unit_price_base == 97
