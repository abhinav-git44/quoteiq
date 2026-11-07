"""SYNTHETIC DEMONSTRATION DATA — fictional RFx, vendors and questionnaire.

All companies, addresses, people and figures here are invented for the Aerchain
take-home demo. This module holds only what a buyer would *author* (the RFx, the
vendor master, the questionnaire) and what vendors submit through a structured
portal form (questionnaire answers). Vendor *quotations* are NOT here: they exist
only as messy documents in demo_data/ and must go through the extraction pipeline.
"""
from __future__ import annotations

RFX = {
    "reference": "RFX-2026-0147",
    "title": "Annual rate contract — corrugated packaging, Chakan plant",
    "category": "Packaging / Corrugated",
    "description": (
        "Annual rate contract for 30 corrugated packaging items used across the "
        "home-appliance assembly lines at the Chakan (Pune) plant."
    ),
    "business_justification": "Consolidate 9 ad-hoc suppliers; current contract expires 31 Dec 2026.",
    "delivery_location": "Plant 2, MIDC Chakan Phase II, Pune 410501 (fictional)",
    "issue_date": "2026-10-20",
    "submission_deadline": "2026-10-30",
    "currency": "INR",
    "required_delivery_days": 15,
    "payment_terms": "45 days from invoice (buyer standard)",
    "commercial_terms": "Prices per unit of measure stated per line, ex-GST, delivered Chakan (DAP).",
    "status": "PUBLISHED",
}

# kind drives the weight model in normalization/weight.py
_ITEMS = [
    # id, code, name, kind, L, W, H, ply, gsm, bs, qty, uom, extra
    ("L01", "CB3-S", "3-ply corrugated box — small", "rsc", 200, 150, 100, 3, 450, 7, 100000, "pcs", {}),
    ("L02", "CB3-M", "3-ply corrugated box — medium", "rsc", 300, 200, 150, 3, 480, 8, 80000, "pcs", {}),
    ("L03", "CB3-L", "3-ply corrugated box — large", "rsc", 400, 300, 250, 3, 520, 9, 50000, "pcs", {}),
    ("L04", "CB5-S", "5-ply corrugated box — small", "rsc", 250, 200, 150, 5, 750, 12, 60000, "pcs", {}),
    ("L05", "CB5-M", "5-ply corrugated box — medium", "rsc", 400, 300, 300, 5, 820, 14, 50000, "pcs", {}),
    ("L06", "CB5-L", "5-ply corrugated box — large", "rsc", 600, 400, 400, 5, 900, 16, 30000, "pcs", {}),
    ("L07", "HD7-01", "Heavy-duty 7-ply corrugated box", "rsc", 600, 500, 500, 7, 1350, 22, 10000, "pcs", {}),
    ("L08", "DW-SC1", "Double-wall shipping carton (BC flute)", "rsc", 500, 400, 350, 5, 880, 15, 25000, "pcs", {}),
    ("L09", "PRT-2C", "Printed corrugated carton, 2-colour flexo", "rsc", 350, 250, 200, 3, 500, 9, 75000, "pcs", {"printed": True}),
    ("L10", "PLN-01", "Plain corrugated carton", "rsc", 350, 250, 200, 3, 480, 8, 75000, "pcs", {}),
    ("L11", "DCB-M1", "Die-cut corrugated mailer box (E-flute)", "die_cut", 300, 220, 80, 3, 420, 7, 60000, "pcs", {"die_cut": True}),
    ("L12", "SHT-3P", "Corrugated sheet, 3-ply", "sheet", 1200, 1000, None, 3, 450, 7, 40000, "pcs", {}),
    ("L13", "ROL-2P", "Corrugated roll, 2-ply, 1000 mm × 50 m", "roll", None, None, None, 2, 280, None, 3000, "roll",
     {"roll_width_mm": 1000, "roll_length_m": 50}),
    ("L14", "PRT-12", "Partition insert, 12-cell (1 L bottles)", "insert", None, None, None, 3, 450, None, 40000, "set", {"area_m2": 0.32}),
    ("L15", "DIV-38", "Corrugated divider pad 380 × 280 mm", "pad", 380, 280, None, 3, 420, None, 100000, "pcs", {}),
    ("L16", "BTL-06", "Bottle packaging insert, 6-cell", "insert", None, None, None, 3, 420, None, 50000, "set", {"area_m2": 0.18}),
    ("L17", "EDG-50", "Edge protector 50 × 50 × 5 mm, 1000 mm long", "edge", None, None, None, None, None, None, 75000, "pcs", {}),
    ("L18", "TRY-43", "Corrugated tray 400 × 300 × 80 mm", "tray", 400, 300, 80, 3, 450, 7, 40000, "pcs", {}),
    ("L19", "SLV-43", "Corrugated sleeve 400 × 300, height 250 mm", "sleeve", 400, 300, 250, 3, 450, 7, 30000, "pcs", {}),
    ("L20", "IND-75", "Industrial shipping box, 5-ply", "rsc", 700, 500, 450, 5, 950, 17, 15000, "pcs", {}),
    ("L21", "EXP-53", "Export-grade carton with moisture barrier", "rsc", 500, 350, 300, 5, 900, 16, 20000, "pcs", {"export": True}),
    ("L22", "MRC-43", "Moisture-resistant (wax-coated) carton", "rsc", 400, 300, 250, 5, 850, 14, 25000, "pcs", {"moisture": True}),
    ("L23", "RKC-32", "Recycled kraft carton", "rsc", 300, 250, 200, 3, 470, 8, 60000, "pcs", {}),
    ("L24", "FGC-32", "Food-grade carton (virgin kraft inner liner)", "rsc", 300, 200, 120, 3, 460, 8, 50000, "pcs", {"food": True}),
    ("L25", "ECM-35", "E-commerce shipping box", "rsc", 350, 250, 100, 3, 440, 7, 125000, "pcs", {}),
    ("L26", "SLC-25", "Self-locking (crash-lock bottom) carton", "rsc", 250, 200, 150, 3, 460, 8, 50000, "pcs", {"self_lock": True}),
    ("L27", "HLC-86", "Heavy-load carton, 7-ply", "rsc", 800, 600, 500, 7, 1400, 24, 7500, "pcs", {}),
    ("L28", "CUS-54", "Custom-size carton, 5-ply", "rsc", 520, 410, 330, 5, 820, 14, 20000, "pcs", {}),
    ("L29", "PLT-11", "Corrugated pallet box, 7-ply", "pallet_box", 1100, 1000, 800, 7, 1500, 26, 2000, "pcs", {}),
    ("L30", "PPI-DC", "Protective packaging insert, die-cut", "insert", None, None, None, 3, 420, None, 60000, "set", {"area_m2": 0.12}),
]

# Buyer target prices (INR per UOM, ex-GST) — last contract rates, rounded.
_TARGETS = {
    "L01": 4.6, "L02": 8.4, "L03": 14.0, "L04": 13.5, "L05": 36.0, "L06": 66.0, "L07": 150.0,
    "L08": 55.0, "L09": 13.6, "L10": 11.5, "L11": 6.9, "L12": 25.5, "L13": 650.0, "L14": 7.6,
    "L15": 2.3, "L16": 4.3, "L17": 13.0, "L18": 9.6, "L19": 7.0, "L20": 95.0, "L21": 66.0,
    "L22": 60.0, "L23": 10.2, "L24": 7.1, "L25": 7.0, "L26": 6.8, "L27": 270.0, "L28": 60.0,
    "L29": 640.0, "L30": 2.9,
}


def rfx_line_items() -> list[dict]:
    out = []
    for (lid, code, name, kind, L, W, H, ply, gsm, bs, qty, uom, extra) in _ITEMS:
        spec = {"kind": kind, "length_mm": L, "width_mm": W, "height_mm": H, "ply": ply,
                "board_gsm": gsm, "bursting_strength_kg_cm2": bs}
        spec.update(extra)
        dims = f"{L}×{W}×{H} mm" if (L and W and H) else (f"{L}×{W} mm" if (L and W) else "")
        desc_bits = [name]
        if dims and dims not in name:
            desc_bits.append(dims)
        if ply:
            desc_bits.append(f"{ply}-ply")
        if gsm:
            desc_bits.append(f"board {gsm} gsm")
        if bs:
            desc_bits.append(f"BS ≥ {bs} kg/cm²")
        out.append({
            "line_id": lid, "item_code": code, "name": name,
            "description": ", ".join(desc_bits), "spec": spec,
            "quantity": qty, "uom": uom, "target_price_inr": _TARGETS[lid],
            "required_delivery_days": 15, "mandatory": True,
        })
    return out


VENDORS = [
    {"vendor_id": "V-A", "name": "PackPro Industries", "city": "Bhosari, Pune",
     "address": "Plot 14, Fictional Industrial Estate, Bhosari, Pune", "contact": "R. Kulkarni",
     "email": "sales@packpro.example", "categories": ["RSC boxes", "printed cartons", "inserts"],
     "certifications": ["ISO 9001:2015"], "capacity_tpm": 450, "historical_score": 82,
     "submission_format": "xlsx"},
    {"vendor_id": "V-B", "name": "EcoCarton Solutions", "city": "Ranjangaon",
     "address": "Gat 221, Fictional MIDC, Ranjangaon", "contact": "S. Deshpande",
     "email": "quotes@ecocarton.example", "categories": ["RSC boxes", "sheets", "recycled kraft"],
     "certifications": ["ISO 9001:2015", "FSC-COC"], "capacity_tpm": 300, "historical_score": 78,
     "submission_format": "pdf"},
    {"vendor_id": "V-C", "name": "Prime Packaging Ltd.", "city": "Talegaon",
     "address": "Survey 88, Fictional Road, Talegaon Dabhade", "contact": "A. Mehta",
     "email": "a.mehta@primepack.example", "categories": ["RSC boxes", "rolls", "pallet boxes"],
     "certifications": ["ISO 9001:2015 (see certificate)"], "capacity_tpm": 600, "historical_score": 71,
     "submission_format": "docx"},
    {"vendor_id": "V-D", "name": "Shree Corrugators", "city": "Bhosari, Pune",
     "address": "Shed 7, Fictional Lane, Bhosari, Pune", "contact": "P. Jadhav",
     "email": "shreecorr@example.in", "categories": ["RSC boxes", "trays", "sleeves"],
     "certifications": ["ISO 9001:2015"], "capacity_tpm": 120, "historical_score": 85,
     "submission_format": "image"},
    {"vendor_id": "V-E", "name": "GlobalPack Trading", "city": "Navi Mumbai",
     "address": "Unit 402, Fictional Trade Centre, Vashi, Navi Mumbai", "contact": "K. Fernandes",
     "email": "k.fernandes@globalpack-trading.example", "categories": ["imported kraft boxes", "edge protectors"],
     "certifications": ["ISO 9001:2015"], "capacity_tpm": 250, "historical_score": 74,
     "submission_format": "email"},
]

# Questionnaire. pass_rule is evaluated deterministically by quality/eligibility.py.
QUESTIONNAIRE = [
    {"qid": "Q01", "text": "Do you hold a valid ISO 9001 certification? Attach the certificate.",
     "type": "yes_no", "mandatory": True, "pass_rule": {"equals": True, "evidence": "iso9001_certificate"}},
    {"qid": "Q02", "text": "Can you meet the specified bursting strength for every line?",
     "type": "yes_no", "mandatory": True, "pass_rule": {"equals": True}},
    {"qid": "Q03", "text": "Can you supply moisture-resistant / wax-coated grades?",
     "type": "yes_no", "mandatory": False, "pass_rule": {"equals": True}},
    {"qid": "Q04", "text": "Do you issue a certificate of analysis / QC report per batch?",
     "type": "yes_no", "mandatory": True, "pass_rule": {"equals": True}},
    {"qid": "Q05", "text": "Standard lead time from PO (days)?",
     "type": "number", "mandatory": True, "pass_rule": {"max": 15}},
    {"qid": "Q06", "text": "Do you support batch-level traceability (batch no. printed on each bundle)?",
     "type": "yes_no", "mandatory": True, "pass_rule": {"equals": True}},
    {"qid": "Q07", "text": "Monthly converting capacity available for this contract (tonnes)?",
     "type": "number", "mandatory": True, "pass_rule": {"min": 40}},
    {"qid": "Q08", "text": "Do you comply with applicable environmental norms (consent to operate, FSC optional)?",
     "type": "yes_no", "mandatory": False, "pass_rule": {"equals": True}},
    {"qid": "Q09", "text": "Can you provide samples within 7 days?",
     "type": "yes_no", "mandatory": False, "pass_rule": {"equals": True}},
    {"qid": "Q10", "text": "Do you operate a documented CAPA process for quality complaints?",
     "type": "yes_no", "mandatory": True, "pass_rule": {"equals": True}},
]

# Answers as submitted through the (stubbed) supplier portal form.
# Evidence documents are real files in demo_data/ and are read by AI, not trusted from here.
QUESTIONNAIRE_ANSWERS = {
    "V-A": {"Q01": True, "Q02": True, "Q03": True, "Q04": True, "Q05": 12, "Q06": True, "Q07": 90,
            "Q08": True, "Q09": True, "Q10": True},
    "V-B": {"Q01": True, "Q02": True, "Q03": False, "Q04": True, "Q05": 14, "Q06": True, "Q07": 60,
            "Q08": True, "Q09": True, "Q10": True},
    # Says "yes" to ISO — but the attached certificate expired. The evidence check must catch it.
    "V-C": {"Q01": True, "Q02": True, "Q03": True, "Q04": True, "Q05": 15, "Q06": True, "Q07": 120,
            "Q08": True, "Q09": True, "Q10": True},
    # Left the mandatory traceability question blank -> must stay PENDING, never auto-PASS.
    "V-D": {"Q01": True, "Q02": True, "Q03": True, "Q04": True, "Q05": 10, "Q06": None, "Q07": 45,
            "Q08": True, "Q09": True, "Q10": True},
    "V-E": {"Q01": True, "Q02": True, "Q03": False, "Q04": True, "Q05": 14, "Q06": True, "Q07": 70,
            "Q08": True, "Q09": False, "Q10": True},
}

CERTIFICATES = {
    # vendor_id: (certificate number, valid_from, valid_until)
    "V-A": ("QMS-IN-24-55102", "2024-06-01", "2027-05-31"),
    "V-B": ("QMS-IN-25-11873", "2025-02-15", "2028-02-14"),
    "V-C": ("QMS-IN-23-04419", "2023-04-01", "2026-03-31"),  # expired before RFx issue date
    "V-D": ("QMS-IN-24-77810", "2024-09-10", "2027-09-09"),
    "V-E": ("QMS-IN-25-30021", "2025-07-01", "2028-06-30"),
}

# Assumed demonstration exchange rates — NOT live market rates.
EXCHANGE_RATES = [
    {"from_currency": "USD", "to_currency": "INR", "rate": 88.50, "rate_date": "2026-10-30",
     "source": "Assumed demo rate (not live)", "rate_type": "ASSUMED_DEMO"},
    {"from_currency": "EUR", "to_currency": "INR", "rate": 96.00, "rate_date": "2026-10-30",
     "source": "Assumed demo rate (not live)", "rate_type": "ASSUMED_DEMO"},
    {"from_currency": "GBP", "to_currency": "INR", "rate": 112.00, "rate_date": "2026-10-30",
     "source": "Assumed demo rate (not live)", "rate_type": "ASSUMED_DEMO"},
]
