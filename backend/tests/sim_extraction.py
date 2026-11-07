"""TEST-ONLY: emulate a competent model's record_quotation output for the demo documents.

This is NOT used by the application. It exists so the deterministic layers (grounding,
normalization, eligibility, optimizer, analyst tools, exports) can be tested end-to-end
without network access. Values come from ground_truth.json; citations are located in the
REAL parsed segments, so grounding checks run against the actual documents.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.demo.catalog import rfx_line_items
from app.domain.extraction import SourceDocument
from app.extraction.grounding import norm, value_in_text

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo_data"
GT = json.loads((DEMO / "ground_truth.json").read_text())
LINES = {l["line_id"]: l for l in rfx_line_items()}

FILES = {"V-A": "vendor_a_packpro_quotation.xlsx", "V-B": "vendor_b_ecocarton_quotation.pdf",
         "V-C": "vendor_c_prime_quotation.docx", "V-D": "vendor_d_shree_quotation_photo.jpg",
         "V-E": "vendor_e_globalpack_email.eml"}


def _size(l):
    s = l["spec"]
    if s.get("length_mm") and s.get("width_mm") and s.get("height_mm"):
        return f"{s['length_mm']}x{s['width_mm']}x{s['height_mm']}"
    if s.get("length_mm") and s.get("width_mm"):
        return f"{s['length_mm']}x{s['width_mm']}"
    return None


def seg_with(doc: SourceDocument, *needles, value=None, avoid=()):
    best = None
    for s in doc.segments:
        t = norm(s.text)
        if any(norm(a) in t for a in avoid):
            continue
        if all(norm(n) in t for n in needles if n) and (value is None or value_in_text(value, s.text)):
            return s
        if value is not None and value_in_text(value, s.text) and best is None and any(norm(n) in t for n in needles if n):
            best = s
    return best


def cite(seg, value=None):
    if seg is None:
        return {"segment_id": None, "snippet": None, "value": value}
    t = seg.text
    return {"segment_id": seg.id, "snippet": t[:200], "value": value}


def header(doc, vid):
    H = {
        "V-A": dict(name=("PACKPRO INDUSTRIES", "PackPro Industries"), ref=("PPI/Q/26-27/0418",), date=("27-Oct-2026", "2026-10-27"),
                    ccy=("Rate (Rs.)", "INR"), validity=("Validity", 30), pay=("Payment: 45", 45), dmin=("Delivery: 12", 12),
                    dmax=("Delivery: 12", 12), freight=("Freight: Included", "INCLUDED", None, None), tax=("GST @ 12%", "EXTRA", 12)),
        "V-B": dict(name=("EcoCarton Solutions", "EcoCarton Solutions"), ref=("EC/Q/2026/0912",), date=("28.10.2026", "2026-10-28"),
                    ccy=("Unit Rate", "INR"), validity=("Validity: 30", 30), pay=("Payment: 45", 45), dmin=("Delivery: 14", 14),
                    dmax=("Delivery: 14", 14), freight=("14,000 per truck", "EXTRA_PER_LOAD", 14000, 4), tax=("GST @ 12%", "EXTRA", 12)),
        "V-C": dict(name=("PRIME PACKAGING LTD.", "Prime Packaging Ltd."), ref=("PPL/MKT/2026/331",), date=("29th October 2026", "2026-10-29"),
                    ccy=("Rate (Rs.)", "INR"), validity=("valid for 45 days", 45), pay=("within 60 days", 60), dmin=("15 to 18 days", 15),
                    dmax=("15 to 18 days", 18), freight=("inclusive of delivery", "INCLUDED", None, None), tax=("GST @ 12%", "EXTRA", 12)),
        "V-D": dict(name=("SHREE CORRUGATORS", "Shree Corrugators"), ref=("SC/26-27/118",), date=("26/10/2026", "2026-10-26"),
                    ccy=("Rate Rs", "INR"), validity=("valid 15", 15), pay=("Payment 30", 30), dmin=("Delivery 10", 10),
                    dmax=("Delivery 10", 10), freight=("Transport", "EXTRA_PER_UNIT", 2.5, None), tax=("GST 12%", "EXTRA", 12)),
        "V-E": dict(name=("GlobalPack Trading |", "GlobalPack Trading"), ref=None, date=("Date:", "2026-10-29"),
                    ccy=("USD 0.55", "USD"), validity=("valid 15 days", 15), pay=("Payment 30 days LC", 30), dmin=("2-3 weeks", 14),
                    dmax=("2-3 weeks", 21), freight=("Freight extra at actuals", "EXTRA_AT_ACTUALS", None, None), tax=None),
    }[vid]

    def tv(key, idx=1):
        spec = H[key]
        if spec is None:
            return {"segment_id": None, "snippet": None, "value": None}
        s = seg_with(doc, spec[0])
        return cite(s, spec[idx] if len(spec) > idx else spec[0])
    fr = H["freight"]
    fs = seg_with(doc, fr[0])
    tx = H["tax"]
    ts = seg_with(doc, tx[0]) if tx else None
    return {
        "vendor_name": tv("name"), "quotation_ref": tv("ref", 0) if H["ref"] else {"value": None},
        "quotation_date": tv("date"), "currency": tv("ccy"), "validity_days": tv("validity"),
        "payment_terms_text": cite(seg_with(doc, H["pay"][0]), seg_with(doc, H["pay"][0]).text if seg_with(doc, H["pay"][0]) else None),
        "payment_days": tv("pay"), "delivery_days_min": tv("dmin"), "delivery_days_max": tv("dmax"),
        "freight": {**cite(fs), "basis": fr[1], "amount": fr[2], "loads": fr[3], "currency": None},
        "tax": {**cite(ts), "basis": tx[1] if tx else "UNSPECIFIED", "rate_pct": tx[2] if tx else None},
    }


def simulated_quotation(vid: str, doc: SourceDocument, perturb: dict | None = None) -> dict:
    gt = GT["vendors"][vid]
    perturb = perturb or {}
    lines, unresolved = [], []
    for lid, g in gt["lines"].items():
        if g["status"] in ("NOT_QUOTED",):
            continue
        rl = LINES[lid]
        if g["status"] == "NEEDS_CLARIFICATION":
            continue
        price = g["price"]
        flags = list(g.get("flags", []))
        uom = g["price_uom"]
        size = _size(rl)
        if vid == "V-E":
            ply = rl["spec"].get("ply")
            needle = {"KG": ("sheets" if lid == "L12" else f"{ply} ply"),
                      "THOUSAND": {"L14": "partitions", "L15": "divider", "L16": "bottle"}.get(lid),
                      "PIECE": "edge protectors"}[uom]
            s = seg_with(doc, needle)
            if uom == "KG":
                flags.append("CATEGORY_PRICE")
            conf = "MEDIUM" if lid in ("L23", "L25", "L12") else "HIGH"
            basis = {"KG": "/kg", "THOUSAND": "per 1000", "PIECE": "each"}[uom]
        else:
            kw = [w for w in norm(rl["name"]).replace(",", " ").split() if len(w) > 3 and w not in ("corrugated", "carton", "box")][:1]
            s = (seg_with(doc, size, *kw, value=price) or seg_with(doc, size, value=price)) if size else None
            if s is None and vid == "V-D" and size:
                s = seg_with(doc, size, *kw)
            if s is None:
                for seg in doc.segments:
                    if value_in_text(price, seg.text) and (not size or norm(size) in norm(seg.text) or "drg" in seg.text.lower()
                                                           or rl["name"].split()[0].lower() in seg.text.lower()):
                        s = seg
                        break
            if s is None and size:
                s = seg_with(doc, size)
            conf = "HIGH"
            basis = {"HUNDRED": "Per 100 Nos", "BUNDLE": "Bundle of 25", "BOX": "Box", "PIECE": "Per Pc",
                     "SET": "Per Set", "ROLL": "Per Roll"}.get(uom, uom)
        if vid == "V-D" and lid == "L19":
            flags.append("OCR_VISION_DISAGREE")
        if vid == "V-A" and lid == "L07":
            flags.append("SPEC_DEVIATION")
        if lid in perturb:
            price = perturb[lid]
        lines.append({**cite(s), "value": None, "vendor_line_ref": None,
                      "vendor_description": (s.text[:80] if s else rl["name"]), "rfx_line_id": lid,
                      "match_basis": "dims/ply/type", "match_confidence": conf, "quantity": rl["quantity"],
                      "price": price, "price_currency": None, "price_basis_text": basis, "price_uom": uom,
                      "units_per_price_uom": g.get("pack_size"), "line_discount_pct": g.get("line_discount_pct"),
                      "line_total": None, "delivery_days": None, "flags": flags,
                      "vendor_spec_note": "BS 20 vs RFx ≥22" if (vid == "V-A" and lid == "L07") else None})
    discounts = []
    if vid == "V-B":
        s = seg_with(doc, "special discount of 4%")
        discounts.append({**cite(s), "kind": "PERCENT", "value": 4, "scope": "ORDER", "rfx_line_ids": [],
                          "condition_type": "ALL_QUOTED_ITEMS_AWARDED", "condition_text": "PO placed for all items quoted",
                          "applies_to": "BASIC_VALUE"})
    if vid == "V-C":
        s = seg_with(doc, "cash discount of 2%")
        discounts.append({**cite(s), "kind": "PERCENT", "value": 2, "scope": "ORDER", "condition_type": "EARLY_PAYMENT",
                          "condition_value": 10, "condition_text": "payment within 10 days", "applies_to": "INVOICE_VALUE"})
        s = seg_with(doc, "Rs. 31.50")
        discounts.append({**cite(s), "kind": "ALTERNATE_PRICE", "value": 31.5, "scope": "LINE", "rfx_line_ids": ["L05"],
                          "condition_type": "MIN_QUANTITY", "condition_value": 75000,
                          "condition_text": "annual quantity increased to 75,000 nos", "applies_to": "UNIT_PRICE"})
    if vid == "V-E":
        s = seg_with(doc, "rest same as last year")
        ids = [lid for lid, g in gt["lines"].items() if g["status"] == "NEEDS_CLARIFICATION"]
        unresolved.append({**cite(s), "text": "rest same as last year", "rfx_line_ids": ids,
                           "reason": "No prior-year rates in this RFx; price cannot be determined"})
    for l in lines:
        l.pop("value", None)
    return {"header": header(doc, vid), "discounts": discounts, "line_items": lines,
            "unresolved_references": unresolved, "document_warnings": []}


def tool_response(payload: dict, name="record_quotation") -> dict:
    return {"id": "msg_test", "type": "message", "role": "assistant", "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "toolu_test", "name": name, "input": payload}]}
