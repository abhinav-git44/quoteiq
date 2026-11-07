"""Deterministic verification of model output against the source document.

The model's own confidence is one weak input. The score that drives review is built
from checks we can actually verify: is the cited snippet really in the document, is the
number really in the snippet, does qty x price reconcile with the line total, do the
dimensions/ply match the RFx line, what did OCR think of that row.

Scores are heuristic indicators (0-100), not calibrated probabilities.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from app.domain.extraction import Check, LineFlag, LLMLine, Segment, SourceDocument

PENALTY = {
    "snippet_not_found": 45, "snippet_other_segment": 8, "snippet_fuzzy": 5,
    "value_not_in_snippet": 35, "ocr_low": 30, "ocr_medium": 12,
    "match_medium": 10, "match_low": 25, "spec_conflict": 35, "spec_deviation": 10,
    "arithmetic": 25, "duplicate": 30, "illegible": 60, "handwritten": 22, "ocr_vision": 25,
    "category_price": 8, "no_price": 60,
}

_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_DIMS = re.compile(r"(\d{2,4})\s*(?:mm)?\s*[x×X*]\s*(\d{2,4})(?:\s*(?:mm)?\s*[x×X*]\s*(\d{2,4}))?")
_PLY = re.compile(r"(\d)\s*-?\s*ply", re.I)
_BS = re.compile(r"\bBS\s*(?:≥|>=)?\s*(\d+(?:\.\d+)?)", re.I)


def norm(t: str | None) -> str:
    t = (t or "").lower()
    for a, b in (("×", "x"), ("₹", "rs"), ("–", "-"), ("—", "-"), (" ", " "), ("’", "'"), ("‘", "'")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def numbers_in(text: str | None) -> list[float]:
    out = []
    for m in _NUM.findall(text or ""):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def value_in_text(value: float | None, text: str | None) -> bool:
    if value is None:
        return False
    return any(abs(n - value) <= max(0.005, abs(value) * 1e-6) for n in numbers_in(text))


def _partial_ratio(needle: str, hay: str) -> float:
    if not needle or not hay:
        return 0.0
    if needle in hay:
        return 1.0
    if len(needle) > len(hay):
        return SequenceMatcher(None, needle, hay).ratio()
    best = 0.0
    step = max(1, len(needle) // 10)
    for i in range(0, len(hay) - len(needle) + 1, step):
        r = SequenceMatcher(None, needle, hay[i:i + len(needle)]).ratio()
        if r > best:
            best = r
            if best > 0.98:
                break
    return best


def locate_snippet(doc: SourceDocument, segment_id: str | None, snippet: str | None) -> tuple[str, Optional[Segment], float]:
    """Returns (status, segment, ratio). status in EXACT, FUZZY, OTHER_SEGMENT, NOT_FOUND, NO_CITATION."""
    if not snippet:
        return "NO_CITATION", doc.segment(segment_id), 0.0
    sn = norm(snippet)
    seg = doc.segment(segment_id)
    if seg is not None:
        r = _partial_ratio(sn, norm(seg.text))
        if r >= 0.999:
            return "EXACT", seg, r
        if r >= 0.85:
            return "FUZZY", seg, r
    best, best_seg = 0.0, None
    for s in doc.segments:
        r = _partial_ratio(sn, norm(s.text))
        if r > best:
            best, best_seg = r, s
    if best >= 0.85:
        return "OTHER_SEGMENT", best_seg, best
    return "NOT_FOUND", seg, best


def citation_checks(doc: SourceDocument, segment_id, snippet, value: float | None = None) -> tuple[list[Check], Optional[Segment]]:
    checks: list[Check] = []
    status, seg, ratio = locate_snippet(doc, segment_id, snippet)
    if status == "EXACT":
        checks.append(Check(name="snippet_in_source", passed=True, detail=f"Snippet found verbatim in {seg.id}"))
    elif status == "FUZZY":
        checks.append(Check(name="snippet_in_source", passed=True, detail=f"Snippet ~{ratio:.0%} match in {seg.id}",
                            penalty=PENALTY["snippet_fuzzy"]))
    elif status == "OTHER_SEGMENT":
        checks.append(Check(name="snippet_in_source", passed=True,
                            detail=f"Model cited {segment_id}; snippet actually found in {seg.id}",
                            penalty=PENALTY["snippet_other_segment"]))
    elif status == "NO_CITATION":
        checks.append(Check(name="snippet_in_source", passed=False, detail="No source snippet provided",
                            penalty=PENALTY["snippet_not_found"]))
    else:
        checks.append(Check(name="snippet_in_source", passed=False,
                            detail=f"Snippet not found in document (best match {ratio:.0%})",
                            penalty=PENALTY["snippet_not_found"]))
    if value is not None:
        hay = (seg.text if seg is not None and status != "NOT_FOUND" else "") + " " + (snippet or "")
        in_seg = seg is not None and status != "NOT_FOUND" and value_in_text(value, seg.text)
        if in_seg:
            checks.append(Check(name="value_in_source", passed=True, detail=f"{value:g} appears in source text"))
        else:
            detail = f"{value:g} not found in the source text of {seg.id if seg else 'any segment'}"
            if seg is not None and seg.ocr_confidence is not None:
                detail += f" (OCR read: “{seg.text[-60:]}”)"
            checks.append(Check(name="value_in_source", passed=False, detail=detail, penalty=PENALTY["value_not_in_snippet"]))
        _ = hay
    if seg is not None and seg.ocr_confidence is not None:
        c = seg.ocr_confidence
        if c < 60:
            checks.append(Check(name="ocr_quality", passed=False, detail=f"OCR confidence {c:.0f}/100", penalty=PENALTY["ocr_low"]))
        elif c < 80:
            checks.append(Check(name="ocr_quality", passed=False, detail=f"OCR confidence {c:.0f}/100", penalty=PENALTY["ocr_medium"]))
        else:
            checks.append(Check(name="ocr_quality", passed=True, detail=f"OCR confidence {c:.0f}/100"))
    return checks, (seg if status != "NOT_FOUND" else None)


def _dims(text: str) -> list[tuple[int, ...]]:
    out = []
    for m in _DIMS.finditer(text or ""):
        out.append(tuple(sorted(int(g) for g in m.groups() if g)))
    return out


def spec_checks(rfx_line: dict, line: LLMLine) -> list[Check]:
    spec = rfx_line.get("spec", {})
    rfx_dims = tuple(sorted(int(d) for d in (spec.get("length_mm"), spec.get("width_mm"), spec.get("height_mm")) if d))
    text = f"{line.vendor_description} {line.snippet or ''}"
    checks: list[Check] = []
    vd = _dims(text)
    if rfx_dims and vd:
        ok = any(d == rfx_dims or (len(d) == 2 and set(d) <= set(rfx_dims)) for d in vd)
        checks.append(Check(name="dimensions_match", passed=ok,
                            detail=("Dimensions match RFx " if ok else f"Vendor dims {vd[0]} ≠ RFx ")
                            + "×".join(map(str, rfx_dims)),
                            penalty=0 if ok else PENALTY["spec_conflict"]))
    vp = _PLY.findall(text)
    if spec.get("ply") and vp:
        ok = int(vp[0]) == int(spec["ply"])
        checks.append(Check(name="ply_match", passed=ok, detail=f"Vendor {vp[0]}-ply vs RFx {spec['ply']}-ply",
                            penalty=0 if ok else PENALTY["spec_conflict"]))
    vb = _BS.findall(text)
    if spec.get("bursting_strength_kg_cm2") and vb:
        ok = float(vb[0]) >= float(spec["bursting_strength_kg_cm2"])
        checks.append(Check(name="bursting_strength", passed=ok,
                            detail=f"Vendor BS {vb[0]} vs RFx ≥ {spec['bursting_strength_kg_cm2']}",
                            penalty=0 if ok else PENALTY["spec_deviation"]))
    return checks


def line_checks(doc: SourceDocument, rfx_line: dict | None, line: LLMLine) -> tuple[list[Check], Optional[Segment]]:
    checks, seg = citation_checks(doc, line.segment_id, line.snippet, line.price)
    if line.price is None:
        checks.append(Check(name="price_present", passed=False, detail="No legible price recorded", penalty=PENALTY["no_price"]))
    if line.match_confidence == "MEDIUM":
        checks.append(Check(name="match_confidence", passed=None, detail=f"Model match MEDIUM: {line.match_basis}", penalty=PENALTY["match_medium"]))
    elif line.match_confidence == "LOW":
        checks.append(Check(name="match_confidence", passed=False, detail=f"Model match LOW: {line.match_basis}", penalty=PENALTY["match_low"]))
    if rfx_line:
        checks += spec_checks(rfx_line, line)
    if line.line_total is not None and line.price is not None and line.quantity:
        pack = line.units_per_price_uom or {"HUNDRED": 100, "THOUSAND": 1000}.get(line.price_uom.value)
        units = line.quantity / pack if (pack and line.price_uom.value in ("HUNDRED", "THOUSAND", "BUNDLE")) else line.quantity
        expected = units * line.price * (1 - (line.line_discount_pct or 0) / 100)
        ok = abs(expected - line.line_total) <= max(1.0, 0.01 * abs(line.line_total))
        checks.append(Check(name="arithmetic", passed=ok,
                            detail=f"qty×rate{'×(1−disc)' if line.line_discount_pct else ''} = {expected:,.2f} vs stated {line.line_total:,.2f}",
                            penalty=0 if ok else PENALTY["arithmetic"]))
    flag_pen = {LineFlag.ILLEGIBLE: "illegible", LineFlag.HANDWRITTEN_CORRECTION: "handwritten",
                LineFlag.OCR_VISION_DISAGREE: "ocr_vision", LineFlag.CATEGORY_PRICE: "category_price",
                LineFlag.SPEC_DEVIATION: "spec_deviation", LineFlag.AMBIGUOUS_MATCH: "match_medium"}
    for f in line.flags:
        if f in flag_pen and not (f == LineFlag.ILLEGIBLE and line.price is None):
            checks.append(Check(name=f"flag_{f.value.lower()}", passed=False, detail=f"Model flagged {f.value}",
                                penalty=PENALTY[flag_pen[f]]))
    return checks, seg


def score(checks: list[Check]) -> float:
    return max(0.0, 100.0 - sum(c.penalty for c in checks))


def band(conf: float, high: float, review: float) -> str:
    return "HIGH" if conf >= high else ("MEDIUM" if conf >= review else "LOW")
