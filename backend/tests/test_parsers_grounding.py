from pathlib import Path

import pytest

from app.demo.catalog import rfx_line_items
from app.domain.extraction import LLMLine, LLMQuotation, PriceUOM
from app.extraction import grounding as G
from app.extraction.parsers import UnsupportedDocument, detect_format
from app.extraction.pipeline import validate_quotation
from conftest import parsed, sim_outcome
from sim_extraction import GT

LINES = {l["line_id"]: l for l in rfx_line_items()}


# ---------------------------------------------------------------- parsers
def test_xlsx_rows_have_sheet_row_locators():
    d = parsed("V-A")
    assert d.doc_format == "xlsx"
    rows = [s for s in d.segments if "PPI-" in s.text]
    assert len(rows) == 30
    assert all(s.locator["kind"] == "xlsx_row" and s.locator["sheet"] == "Quotation" for s in rows)


def test_pdf_footnote_is_found_and_marked_fine_print():
    d = parsed("V-B")
    foot = [s for s in d.segments if "special discount of 4%" in s.text]
    assert foot and foot[0].locator.get("fine_print") is True
    assert foot[0].locator["page"] == 2      # buried on page 2


def test_docx_paragraph_commercials_are_segmented():
    d = parsed("V-C")
    assert any("cash discount of 2%" in s.text and s.locator["kind"] == "docx_paragraph" for s in d.segments)
    assert sum(1 for s in d.segments if s.locator["kind"] == "docx_table_row") == 31


def test_email_marks_quoted_history():
    d = parsed("V-E")
    hist = [s for s in d.segments if s.locator.get("quoted_history")]
    assert hist and any("Please quote" in s.text for s in hist)
    assert d.meta["from"].startswith("Kevin")


def test_photo_is_perspective_corrected_and_ocrd():
    d = parsed("V-D")
    assert "Perspective corrected" in " ".join(d.warnings)
    priced_rows = [s for s in d.segments if s.ocr_confidence is not None and G.numbers_in(s.text) and "x" in s.text.lower()]
    assert len(priced_rows) >= 24
    assert d.derived_image_path and Path(d.derived_image_path).exists()


def test_rejects_bad_files(tmp_path):
    p = tmp_path / "x.exe"; p.write_bytes(b"MZ")
    with pytest.raises(UnsupportedDocument):
        detect_format(p)
    p = tmp_path / "fake.pdf"; p.write_bytes(b"hello")
    with pytest.raises(UnsupportedDocument, match="does not match"):
        detect_format(p)
    p = tmp_path / "empty.txt"; p.write_bytes(b"")
    with pytest.raises(UnsupportedDocument, match="empty"):
        detect_format(p)


# ---------------------------------------------------------------- grounding
def test_value_in_text_handles_indian_grouping():
    assert G.value_in_text(463000, "Amount 4,63,000.00")
    assert G.value_in_text(4.6, "rate 4.60 per pc")
    assert not G.value_in_text(8.39, "19. sleeve 400x300x250 8:39")


def test_snippet_location_statuses():
    d = parsed("V-B")
    seg = next(s for s in d.segments if "special discount" in s.text)
    assert G.locate_snippet(d, seg.id, "special discount of 4%")[0] == "EXACT"
    assert G.locate_snippet(d, "S001", "special discount of 4%")[0] == "OTHER_SEGMENT"
    assert G.locate_snippet(d, seg.id, "special discnt of 4 %")[0] in ("FUZZY", "OTHER_SEGMENT")
    assert G.locate_snippet(d, seg.id, "free shipping on everything")[0] == "NOT_FOUND"


def _line(**kw):
    base = dict(vendor_description="x", rfx_line_id="L05", match_basis="t", match_confidence="HIGH", price=10.0,
                price_uom=PriceUOM.PIECE, segment_id=None, snippet=None)
    base.update(kw)
    return LLMLine(**base)


def test_spec_checks_catch_dimension_and_bs_deviation():
    bad = G.spec_checks(LINES["L05"], _line(vendor_description="5 ply box 400x300x250"))
    assert any(c.name == "dimensions_match" and not c.passed for c in bad)
    bs = G.spec_checks(LINES["L07"], _line(rfx_line_id="L07", vendor_description="7 Ply Heavy Duty RSC Box, BS 20"))
    assert any(c.name == "bursting_strength" and not c.passed for c in bs)


def test_simulated_extraction_grounds_cleanly_for_native_formats():
    for vid in ("V-A", "V-B", "V-C"):
        oc = sim_outcome(vid)
        assert all(any(c.name == "snippet_in_source" and c.passed for c in v.checks) for v in oc.lines), vid
        assert all(any(c.name == "value_in_source" and c.passed for c in v.checks) for v in oc.lines), vid


def test_fabricated_price_is_caught():
    """If the model returns a price that is not in the cited source, the line must go to review."""
    oc = sim_outcome("V-A", perturb={"L05": 99.99})
    l5 = next(v for v in oc.lines if v.llm.rfx_line_id == "L05")
    assert l5.review_required and l5.confidence < 70
    assert any(c.name == "value_in_source" and c.passed is False for c in l5.checks)
    assert any(e.code == "LOW_CONFIDENCE" and e.rfx_line_id == "L05" for e in oc.exceptions)


def test_photo_edges_handwriting_and_smudge_go_to_review():
    oc = sim_outcome("V-D")
    by = {v.llm.rfx_line_id: v for v in oc.lines}
    assert by["L19"].review_required                       # smudged: OCR '8:39'
    assert by["L06"].confidence < 90                        # handwritten correction
    assert oc.coverage["L21"] == "NOT_QUOTED" and oc.coverage["L24"] == "NOT_QUOTED"


def test_email_unresolved_reference_becomes_needs_clarification():
    oc = sim_outcome("V-E")
    gt_clar = [l for l, g in GT["vendors"]["V-E"]["lines"].items() if g["status"] == "NEEDS_CLARIFICATION"]
    assert all(oc.coverage[l] == "NEEDS_CLARIFICATION" for l in gt_clar)
    assert any(e.code == "UNRESOLVED_REFERENCE" and e.severity == "BLOCKING" for e in oc.exceptions)


def test_duplicate_matches_flagged():
    d = parsed("V-A")
    seg = next(s for s in d.segments if "PPI-" in s.text)
    q = LLMQuotation.model_validate({
        "header": {k: {"value": None} for k in ("vendor_name", "quotation_ref", "quotation_date", "currency", "validity_days",
                                               "payment_terms_text", "payment_days", "delivery_days_min", "delivery_days_max")}
        | {"freight": {"basis": "UNSPECIFIED"}, "tax": {"basis": "UNSPECIFIED"}},
        "line_items": [_line(rfx_line_id="L01", segment_id=seg.id, snippet=seg.text, price=G.numbers_in(seg.text)[-3]).model_dump(),
                       _line(rfx_line_id="L01", segment_id=seg.id, snippet=seg.text, price=1.0).model_dump()]})
    _, lines, cov, exc = validate_quotation(d, q, rfx_line_items())
    assert any(e.code == "DUPLICATE_MATCH" for e in exc)
    assert any(c.name == "duplicate_match" for v in lines for c in v.checks)
    assert any(e.code == "CURRENCY_UNKNOWN" and e.severity == "BLOCKING" for e in exc)
