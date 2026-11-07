"""Generate the five messy vendor quotations + ISO certificates + ground truth.

SYNTHETIC DEMONSTRATION DATA. Run:  python scripts/generate_documents.py
Outputs to demo_data/. ground_truth.json is used ONLY by scripts/eval_extraction.py
and tests to score the extraction pipeline; the application never reads it.
"""
from __future__ import annotations

import json
import random
import sys
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.demo.catalog import CERTIFICATES, RFX, VENDORS, rfx_line_items  # noqa: E402
from app.normalization.weight import estimate_weight  # noqa: E402

OUT = ROOT / "demo_data"
BUYER = "Kaveri Home Appliances Pvt. Ltd. (fictional)"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_HAND = "/usr/share/fonts/truetype/dejavu/DejaVuSerifCondensed-BoldItalic.ttf"

LINES = rfx_line_items()
BY_ID = {l["line_id"]: l for l in LINES}
RATE_PER_KG = {2: 44, 3: 46, 5: 50, 7: 54}
MODS = [("printed", 1.18), ("export", 1.15), ("moisture", 1.25), ("food", 1.12), ("self_lock", 1.08), ("die_cut", 1.10)]


def base_price(line) -> float:
    s = line["spec"]
    w = estimate_weight(s)
    if not w:
        return 14.0
    m = 1.0
    for k, f in MODS:
        if s.get(k):
            m *= f
    return w.weight_kg * RATE_PER_KG[s["ply"]] * m + 0.8


def size_str(line, sep="x"):
    s = line["spec"]
    if s.get("length_mm") and s.get("width_mm") and s.get("height_mm"):
        return f"{s['length_mm']}{sep}{s['width_mm']}{sep}{s['height_mm']}"
    if s.get("length_mm") and s.get("width_mm"):
        return f"{s['length_mm']}{sep}{s['width_mm']}"
    if s.get("roll_width_mm"):
        return f"{s['roll_width_mm']}mm x {s['roll_length_m']}m"
    return "As per drg."


def fmt_inr(x: float) -> str:
    """Indian digit grouping: 12,34,567.00"""
    neg = x < 0
    x = abs(x)
    whole, frac = f"{x:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return ("-" if neg else "") + whole + "." + frac


# ---------------------------------------------------------------- pricing
rng = random.Random(147)
GT: dict = {"_note": "SYNTHETIC. Used only for evaluation; never read by the app.", "vendors": {}}


def gt_vendor(vid, header):
    GT["vendors"][vid] = {"header": header, "lines": {}}


def gt_line(vid, lid, **kw):
    GT["vendors"][vid]["lines"][lid] = kw


# ---------------------------------------------------------------- Vendor A: XLSX
def vendor_a():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    vid = "V-A"
    gt_vendor(vid, {"currency": "INR", "payment_days": 45, "freight": "INCLUDED", "tax": "EXTRA 12%",
                    "validity_days": 30, "delivery_days": 12, "quotation_ref": "PPI/Q/26-27/0418"})
    per100 = {"L14", "L15", "L16", "L30"}
    disc = {"L01": 3, "L02": 3, "L10": 3, "L25": 3, "L05": 2, "L12": 5}
    words = {
        "rsc": "RSC Box", "die_cut": "Die Cut Mailer", "sheet": "Corr. Sheet", "roll": "Corr. Roll",
        "insert": "Insert", "pad": "Divider Pad", "edge": "Edge Board", "tray": "Tray", "sleeve": "Sleeve",
        "pallet_box": "Pallet Box",
    }
    rows = []
    for l in LINES:
        p = round(base_price(l) * 1.02 * rng.uniform(0.96, 1.04), 2)
        s = l["spec"]
        if l["line_id"] == "L07":
            desc = "7 Ply Heavy Duty RSC Box, BS 20"  # spec deviation vs RFx BS>=22
        else:
            bits = [f"{s['ply']} Ply" if s.get("ply") else "", words[s["kind"]]]
            for k, w in [("printed", "2 Clr Print"), ("export", "Export Qlty w/ PE Lamination"),
                         ("moisture", "Wax Coated"), ("food", "Food Grade Virgin Kraft"),
                         ("self_lock", "Crash Lock Btm"), ("die_cut", "E-Flute")]:
                if s.get(k):
                    bits.append(w)
            if l["line_id"] == "L14":
                bits.append("12 Cell")
            if l["line_id"] == "L16":
                bits.append("6 Cell Bottle")
            if l["line_id"] == "L30":
                bits.append("Protective Die-cut")
            if l["line_id"] == "L23":
                bits.append("Recycled Kraft")
            if l["line_id"] == "L25":
                bits.append("E-com Shipper")
            if l["line_id"] == "L20":
                bits.append("Industrial")
            if l["line_id"] == "L28":
                bits.append("Custom Size")
            desc = " ".join(b for b in bits if b)
        basis = "Per 100 Nos" if l["line_id"] in per100 else ("Per Roll" if l["uom"] == "roll" else "Per Pc")
        rate = round(p * 100, 0) if l["line_id"] in per100 else p
        d = disc.get(l["line_id"], 0)
        units = l["quantity"] / 100 if l["line_id"] in per100 else l["quantity"]
        net = round(units * rate * (1 - d / 100), 2)
        rows.append((s.get("ply") or 0, l, desc, basis, rate, d, net))
        gt_line(vid, l["line_id"], status="QUOTED", price=rate, price_uom="HUNDRED" if l["line_id"] in per100 else ("ROLL" if l["uom"] == "roll" else "PIECE"),
                pack_size=100 if l["line_id"] in per100 else None, currency="INR", line_discount_pct=d or None,
                unit_price_inr_per_rfx_uom=round(p * (1 - d / 100), 4) if l["line_id"] not in per100 else round(rate / 100 * (1 - d / 100), 4),
                snippet_hint=f"{rate:.2f}" if l["line_id"] not in per100 else f"{rate:.0f}")
    rows.sort(key=lambda r: (r[0], r[1]["line_id"]))  # vendor's own ordering: by ply

    wb = Workbook()
    ws = wb.active
    ws.title = "Quotation"
    thin = Side(style="thin", color="999999")
    ws.merge_cells("A1:J1"); ws["A1"] = "PACKPRO INDUSTRIES"
    ws["A1"].font = Font(size=18, bold=True, color="1F3864"); ws["A1"].alignment = Alignment(horizontal="center")
    ws.merge_cells("A2:J2"); ws["A2"] = "Plot 14, Fictional Industrial Estate, Bhosari, Pune | sales@packpro.example"
    ws["A2"].alignment = Alignment(horizontal="center")
    ws["A4"] = "Quotation No:"; ws["C4"] = "PPI/Q/26-27/0418"
    ws["A5"] = "Date:"; ws["C5"] = "27-Oct-2026"
    ws["A6"] = "To:"; ws["C6"] = BUYER
    ws["F4"] = "Your Ref:"; ws["H4"] = RFX["reference"]
    hdr = ["Sr.", "Item Code", "Description", "Size (mm) LxWxH", "Ply", "Qty (Nos)", "Rate (Rs.)", "Rate Basis", "Disc %", "Net Amount (Rs.)"]
    for i, h in enumerate(hdr, start=1):
        c = ws.cell(row=8, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F3864")
        c.alignment = Alignment(wrap_text=True, horizontal="center"); c.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    r = 9
    for n, (_, l, desc, basis, rate, d, net) in enumerate(rows, start=1):
        vals = [n, f"PPI-{4100 + int(l['line_id'][1:]) * 7}", desc, size_str(l), l["spec"].get("ply") or "-",
                l["quantity"], rate, basis, d if d else None, net]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=i, value=v); c.border = Border(top=thin, bottom=thin, left=thin, right=thin)
            if i in (7, 10):
                c.number_format = "#,##0.00"
        r += 1
    ws.cell(row=r, column=9, value="Total").font = Font(bold=True)
    ws.cell(row=r, column=10, value=f"=SUM(J9:J{r - 1})").number_format = "#,##0.00"
    r += 2
    for t in ["Terms & Conditions:",
              "1. GST @ 12% extra as applicable.",
              "2. Freight: Included up to your Chakan plant.",
              "3. Payment: 45 days from date of invoice.",
              "4. Validity: 30 days from quotation date.",
              "5. Delivery: 12 days from receipt of PO.",
              "6. Rates for inserts & dividers are per 100 Nos."]:
        ws.cell(row=r, column=1, value=t); r += 1
    ws.cell(row=r + 1, column=1, value="For PackPro Industries — R. Kulkarni, Sales Manager")
    widths = [5, 12, 44, 18, 5, 11, 11, 13, 7, 17]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    wb.save(OUT / "vendor_a_packpro_quotation.xlsx")


# ---------------------------------------------------------------- Vendor B: PDF
def vendor_b():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pdfmetrics.registerFont(TTFont("DV", FONT)); pdfmetrics.registerFont(TTFont("DVB", FONT_B))
    vid = "V-B"
    missing = {"L13", "L17", "L29"}
    gt_vendor(vid, {"currency": "INR", "payment_days": 45, "freight": "EXTRA_FIXED 14000 x 4 trucks = 56000",
                    "tax": "EXTRA 12%", "validity_days": 30, "delivery_days": 14, "quotation_ref": "EC/Q/2026/0912",
                    "discounts": [{"type": "PERCENT", "value": 4, "scope": "ORDER", "condition": "ALL_QUOTED_ITEMS_AWARDED",
                                   "where": "footnote"}]})
    data = [["S.No", "Description", "Dimensions (mm)", "Qty", "Unit Rate (₹)", "Amount (₹)"]]
    basic = 0.0
    n = 0
    for l in LINES:
        if l["line_id"] in missing:
            gt_line(vid, l["line_id"], status="NOT_QUOTED"); rng.random(); continue
        p = round(base_price(l) * 0.98 * rng.uniform(0.95, 1.05), 2)
        n += 1
        amt = p * l["quantity"]; basic += amt
        name = l["name"].replace("—", "-")
        data.append([str(n), Paragraph(name, ParagraphStyle("c", fontName="DV", fontSize=8, leading=10)),
                     size_str(l), f"{l['quantity']:,}", fmt_inr(p), fmt_inr(amt)])
        gt_line(vid, l["line_id"], status="QUOTED", price=p, price_uom="ROLL" if l["uom"] == "roll" else ("SET" if l["uom"] == "set" else "PIECE"),
                pack_size=None, currency="INR", unit_price_inr_per_rfx_uom=p, snippet_hint=fmt_inr(p))
    data.append(["", "", "", "", "Basic Value*", fmt_inr(basic)])
    doc = SimpleDocTemplate(str(OUT / "vendor_b_ecocarton_quotation.pdf"), pagesize=A4,
                            leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=15 * mm)
    ss = getSampleStyleSheet()
    H = ParagraphStyle("h", parent=ss["Title"], fontName="DVB", textColor=colors.HexColor("#2E7D32"), fontSize=20)
    N = ParagraphStyle("n", parent=ss["Normal"], fontName="DV", fontSize=9, leading=12)
    S = ParagraphStyle("s", parent=N, fontSize=6.5, leading=8, textColor=colors.HexColor("#555555"))
    story = [Paragraph("EcoCarton Solutions", H),
             Paragraph("Gat 221, Fictional MIDC, Ranjangaon · quotes@ecocarton.example · GSTIN 27XXXXX0000X1Z0 (fictional)", N),
             Spacer(1, 6 * mm),
             Paragraph("<b>QUOTATION</b> &nbsp; Ref: EC/Q/2026/0912 &nbsp;&nbsp; Date: 28.10.2026", N),
             Paragraph(f"To: Purchase Dept., {BUYER} &nbsp; | &nbsp; Your enquiry: {RFX['reference']}", N),
             Spacer(1, 4 * mm)]
    t = Table(data, colWidths=[12 * mm, 62 * mm, 32 * mm, 20 * mm, 24 * mm, 30 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "DV", 8), ("FONT", (0, 0), (-1, 0), "DVB", 8),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F5E9")),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [t, Spacer(1, 5 * mm),
              Paragraph("<b>Commercial terms</b>", N),
              Paragraph("Taxes: GST @ 12% extra. Freight: Extra @ ₹14,000 per truck load; approx. 4 loads estimated for the complete order.", N),
              Paragraph("Payment: 45 days from invoice. Validity: 30 days. Delivery: 14 days from PO, in two lots.", N),
              Paragraph("Items not listed above are not in our current manufacturing range.", N),
              Spacer(1, 10 * mm),
              Paragraph("For EcoCarton Solutions<br/>S. Deshpande, Business Development", N),
              Spacer(1, 18 * mm),
              Paragraph("* A special discount of 4% on the Basic Value will be extended if the purchase order is placed "
                        "for all items quoted above. Discount not applicable on freight and taxes. E&OE.", S)]
    doc.build(story)


# ---------------------------------------------------------------- Vendor C: DOCX
def vendor_c():
    from docx import Document
    from docx.shared import Pt

    vid = "V-C"
    gt_vendor(vid, {"currency": "INR", "payment_days": 60, "freight": "INCLUDED", "tax": "EXTRA 12%",
                    "validity_days": 45, "delivery_days": "15-18", "quotation_ref": "PPL/MKT/2026/331",
                    "discounts": [{"type": "PERCENT", "value": 2, "scope": "ORDER", "condition": "EARLY_PAYMENT 10 days",
                                   "where": "paragraph"},
                                  {"type": "ALTERNATE_PRICE", "line": "L05", "value": 31.50,
                                   "condition": "quantity increased to 75,000 nos", "where": "paragraph"}]})
    d = Document()
    st = d.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10.5)
    d.add_heading("PRIME PACKAGING LTD.", level=1)
    d.add_paragraph("Survey 88, Fictional Road, Talegaon Dabhade · a.mehta@primepack.example")
    d.add_paragraph("Ref: PPL/MKT/2026/331                                                     Date: 29th October 2026")
    d.add_paragraph(f"To,\nThe Purchase Manager,\n{BUYER}\nChakan, Pune")
    d.add_paragraph(f"Subject: Our best offer against your enquiry {RFX['reference']} for corrugated packaging")
    d.add_paragraph("Dear Sir/Madam,")
    d.add_paragraph(
        "Thank you for the opportunity. We are pleased to quote our most competitive rates for your annual requirement "
        "as tabulated below. Our prices are inclusive of delivery to your Chakan plant, so you will not see any separate "
        "transport charge from us. GST @ 12% will be charged extra as applicable.")
    tbl_rows = []
    for l in LINES:
        p = round(base_price(l) * 0.94 * rng.uniform(0.96, 1.04), 2)
        lid = l["line_id"]
        if lid in ("L15", "L16"):
            rate, per = round(p * 25, 2), "Bundle of 25"
            gt_line(vid, lid, status="QUOTED", price=rate, price_uom="BUNDLE", pack_size=25, currency="INR",
                    unit_price_inr_per_rfx_uom=round(rate / 25, 4), snippet_hint=f"{rate:,.2f}")
        elif lid == "L17":
            rate, per = round(14.0 * 0.94 * 20, 2), "Box"
            gt_line(vid, lid, status="NOT_COMPARABLE", price=rate, price_uom="BOX", pack_size=None, currency="INR",
                    reason="Priced per box; pieces per box not stated", snippet_hint=f"{rate:,.2f}")
        elif lid == "L13":
            rate, per = p, "Roll"
            gt_line(vid, lid, status="QUOTED", price=rate, price_uom="ROLL", pack_size=None, currency="INR",
                    unit_price_inr_per_rfx_uom=rate, snippet_hint=f"{rate:,.2f}")
        else:
            rate, per = p, "Pc" if l["uom"] == "pcs" else "Set"
            gt_line(vid, lid, status="QUOTED", price=rate, price_uom="PIECE" if per == "Pc" else "SET", pack_size=None,
                    currency="INR", unit_price_inr_per_rfx_uom=rate, snippet_hint=f"{rate:,.2f}")
        tbl_rows.append((l, rate, per))
    t = d.add_table(rows=1, cols=6)
    t.style = "Table Grid"
    for i, h in enumerate(["Sl.", "Particulars", "Size", "Qty", "Rate (Rs.)", "Per"]):
        t.rows[0].cells[i].text = h
    for n, (l, rate, per) in enumerate(tbl_rows, start=1):
        cells = t.add_row().cells
        name = l["name"].replace("—", "-").replace("corrugated ", "").title()
        for i, v in enumerate([str(n), name, size_str(l), f"{l['quantity']:,}", f"{rate:,.2f}", per]):
            cells[i].text = v
    d.add_paragraph("")
    d.add_paragraph(
        "Regarding commercials: payment shall be made within 60 days from the date of invoice. However, should you "
        "prefer, a cash discount of 2% on the invoice value is available for payment received within 10 days. "
        "This offer remains valid for 45 days, and we will be able to commence deliveries 15 to 18 days after receipt "
        "of your purchase order.")
    d.add_paragraph(
        "We would also like to draw your attention to the 5-ply medium boxes (400x300x300): if the annual quantity can "
        "be increased to 75,000 nos, we can offer a special rate of Rs. 31.50 per piece against the rate tabulated above.")
    d.add_paragraph("Our ISO 9001 certificate is attached for your records. We look forward to your valued order.")
    d.add_paragraph("Yours faithfully,\nFor Prime Packaging Ltd.\nA. Mehta, Head — Marketing")
    d.save(OUT / "vendor_c_prime_quotation.docx")


# ---------------------------------------------------------------- Vendor D: angled phone photo
def vendor_d():
    import numpy as np
    import cv2
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    vid = "V-D"
    missing = {"L21", "L24"}
    gt_vendor(vid, {"currency": "INR", "payment_days": 30, "freight": "EXTRA_PER_UNIT 2.50 per piece",
                    "tax": "EXTRA 12%", "validity_days": 15, "delivery_days": 10, "quotation_ref": "SC/26-27/118"})
    W, Hh = 1240, 1754
    page = Image.new("RGB", (W, Hh), (250, 249, 244))
    dr = ImageDraw.Draw(page)
    f = ImageFont.truetype(FONT, 21); fb = ImageFont.truetype(FONT_B, 21); ft = ImageFont.truetype(FONT_B, 42)
    fs = ImageFont.truetype(FONT, 17); fh = ImageFont.truetype(FONT_HAND, 30)
    dr.text((W // 2, 60), "SHREE CORRUGATORS", font=ft, fill=(20, 20, 20), anchor="mm")
    dr.text((W // 2, 105), "Shed 7, Fictional Lane, Bhosari, Pune  |  shreecorr@example.in", font=fs, fill=(40, 40, 40), anchor="mm")
    dr.line((60, 130, W - 60, 130), fill=(0, 0, 0), width=3)
    dr.text((70, 150), "QUOTATION   No. SC/26-27/118", font=fb, fill=(0, 0, 0))
    dr.text((W - 70, 150), "Date: 26/10/2026", font=f, fill=(0, 0, 0), anchor="ra")
    dr.text((70, 185), f"To: {BUYER.replace(' (fictional)', '')}, Chakan   Ref: {RFX['reference']}", font=f, fill=(0, 0, 0))
    cols = [70, 140, 690, 960, 1170]
    y = 240
    dr.rectangle((60, y - 8, W - 60, y + 30), outline=(0, 0, 0), width=2)
    for x, h in zip(cols, ["No", "Item", "Size (mm)", "Rate Rs."]):
        dr.text((x, y), h, font=fb, fill=(0, 0, 0))
    y += 44
    n = 0
    for l in LINES:
        lid = l["line_id"]
        if lid in missing:
            gt_line(vid, lid, status="NOT_QUOTED"); rng.random(); continue
        p = round(base_price(l) * 0.97 * rng.uniform(0.94, 1.06), 2)
        n += 1
        name = l["name"].replace("—", "-").replace("corrugated ", "").replace("Corrugated ", "")
        name = name[:40]
        dr.text((cols[0], y), f"{n}.", font=f, fill=(15, 15, 15))
        dr.text((cols[1], y), name, font=f, fill=(15, 15, 15))
        dr.text((cols[2], y), size_str(l), font=f, fill=(15, 15, 15))
        price_uom = "ROLL" if l["uom"] == "roll" else ("SET" if l["uom"] == "set" else "PIECE")
        if lid == "L06":
            printed = round(p + 4, 2)
            dr.text((cols[3], y), f"{printed:.2f}", font=f, fill=(15, 15, 15))
            dr.line((cols[3] - 4, y + 12, cols[3] + 70, y + 10), fill=(20, 40, 160), width=3)
            dr.text((cols[3] + 82, y - 8), f"{p:.2f}", font=fh, fill=(25, 45, 170))
            gt_line(vid, lid, status="QUOTED", price=p, price_uom=price_uom, currency="INR",
                    unit_price_inr_per_rfx_uom=p, flags=["HANDWRITTEN_CORRECTION"], printed_value=printed,
                    snippet_hint=f"{p:.2f}")
        elif lid == "L19":
            dr.text((cols[3], y), f"{p:.2f}", font=f, fill=(15, 15, 15))
            gt_line(vid, lid, status="QUOTED", price=p, price_uom=price_uom, currency="INR",
                    unit_price_inr_per_rfx_uom=p, flags=["ILLEGIBLE"], snippet_hint=f"{p:.2f}")
            smudge = (cols[3] - 10, y - 6, cols[3] + 95, y + 30)
        else:
            dr.text((cols[3], y), f"{p:.2f}", font=f, fill=(15, 15, 15))
            gt_line(vid, lid, status="QUOTED", price=p, price_uom=price_uom, currency="INR",
                    unit_price_inr_per_rfx_uom=p, snippet_hint=f"{p:.2f}")
        y += 41
    dr.line((60, y + 4, W - 60, y + 4), fill=(0, 0, 0), width=2)
    y += 22
    for t in ["Rates per piece / per set / per roll, ex-works Bhosari. GST 12% extra.",
              "Transport: Rs. 2.50 per piece extra (our vehicle).",
              "Payment 30 days. Delivery 10 days. Offer valid 15 days.",
              "For Shree Corrugators - P. Jadhav (Prop.)"]:
        dr.text((70, y), t, font=f, fill=(15, 15, 15)); y += 34
    # coffee-ish smudge over L19 price
    sm = Image.new("L", (W, Hh), 0)
    ImageDraw.Draw(sm).ellipse(smudge, fill=235)
    sm = sm.filter(ImageFilter.GaussianBlur(9))
    page = Image.composite(Image.new("RGB", (W, Hh), (150, 125, 95)), page, sm)

    # project onto a desk at an angle (phone photo)
    src = np.float32([[0, 0], [W, 0], [W, Hh], [0, Hh]])
    CW, CH = 1700, 2250
    dst = np.float32([[205, 150], [1530, 245], [1460, 2120], [120, 1985]])
    M = cv2.getPerspectiveTransform(src, dst)
    desk = np.full((CH, CW, 3), (62, 92, 128), np.uint8)  # BGR wood-ish
    noise = np.random.default_rng(3).integers(0, 25, (CH, CW, 1), dtype=np.uint8)
    desk = cv2.add(desk, np.repeat(noise, 3, axis=2))
    pg = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
    warped = cv2.warpPerspective(pg, M, (CW, CH))
    mask = cv2.warpPerspective(np.full((Hh, W), 255, np.uint8), M, (CW, CH))
    img = np.where(mask[..., None] > 0, warped, desk)
    # uneven lighting + blur + sensor noise
    gx = np.linspace(0.78, 1.04, CW)[None, :, None]
    gy = np.linspace(1.02, 0.86, CH)[:, None, None]
    img = np.clip(img.astype(np.float32) * gx * gy, 0, 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 1.1)
    img = cv2.add(img, np.random.default_rng(5).integers(0, 8, img.shape, dtype=np.uint8))
    cv2.imwrite(str(OUT / "vendor_d_shree_quotation_photo.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 72])


# ---------------------------------------------------------------- Vendor E: email, USD, per kg
def vendor_e():
    vid = "V-E"
    fx = 88.50
    gt_vendor(vid, {"currency": "USD", "payment_days": 30, "payment_text": "30 days LC", "freight": "EXTRA_AT_ACTUALS",
                    "tax": "UNSPECIFIED", "validity_days": 15, "delivery_days": "14-21", "quotation_ref": None,
                    "unresolved": "rest same as last year's rates"})
    kg = {3: 0.55, 5: 0.59, 7: 0.63}
    kg_lines = {"L01", "L02", "L03", "L04", "L05", "L06", "L07", "L08", "L10", "L12", "L20", "L23", "L25", "L27", "L28"}
    per1000 = {"L14": 88.0, "L15": 33.0, "L16": 50.0}
    for l in LINES:
        lid = l["line_id"]
        if lid in kg_lines:
            w = estimate_weight(l["spec"]).weight_kg
            r = kg[l["spec"]["ply"]]
            gt_line(vid, lid, status="QUOTED", price=r, price_uom="KG", currency="USD",
                    unit_price_inr_per_rfx_uom=round(w * r * fx, 4), derived=True,
                    ambiguity="category price ('3-ply boxes')" if lid in ("L23", "L25") else None)
        elif lid in per1000:
            gt_line(vid, lid, status="QUOTED", price=per1000[lid], price_uom="THOUSAND", pack_size=1000, currency="USD",
                    unit_price_inr_per_rfx_uom=round(per1000[lid] / 1000 * fx, 4))
        elif lid == "L17":
            gt_line(vid, lid, status="QUOTED", price=0.16, price_uom="PIECE", currency="USD",
                    unit_price_inr_per_rfx_uom=round(0.16 * fx, 4))
        else:
            gt_line(vid, lid, status="NEEDS_CLARIFICATION", reason="'rest same as last year' — no prior rates provided")
    body = f"""Hi Priya,

Thanks for sending over the RFx ({RFX['reference']}). Quick reply from my phone, formal offer can follow if needed.

Our rates for this year:
- 3 ply boxes USD 0.55/kg
- 5 ply boxes (incl. the double wall BC flute cartons) USD 0.59/kg
- 7 ply heavy duty USD 0.63/kg
- corrugated sheets same as 3 ply rate
- partitions 12 cell USD 88 per 1000 sets, divider pads USD 33 per 1000, 6-cell bottle inserts USD 50 per 1000 sets
- edge protectors 0.16 each

Printed, wax coated, export, food grade, trays/sleeves, rolls and pallet boxes - rest same as last year.
Freight extra at actuals. Payment 30 days LC. Rates valid 15 days given kraft paper volatility.
Delivery 2-3 weeks from PO.

Regards,
Kevin Fernandes
GlobalPack Trading | Vashi, Navi Mumbai
+91 90000 00000 (fictional)

-----Original Message-----
From: Priya Nair <priya.nair@kaveri-appliances.example>
Sent: 21 October 2026 10:12
Subject: {RFX['reference']} - Request for quotation, corrugated packaging
> Please quote against the attached RFx template for all 30 lines.
"""
    m = EmailMessage()
    m["From"] = "Kevin Fernandes <k.fernandes@globalpack-trading.example>"
    m["To"] = "Priya Nair <priya.nair@kaveri-appliances.example>"
    m["Subject"] = f"RE: {RFX['reference']} - Request for quotation, corrugated packaging"
    m["Date"] = format_datetime(datetime(2026, 10, 29, 21, 47, tzinfo=timezone(timedelta(hours=5, minutes=30))))
    m.set_content(body)
    (OUT / "vendor_e_globalpack_email.eml").write_bytes(bytes(m))


# ---------------------------------------------------------------- certificates
def certificates():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(TTFont("DV", FONT)); pdfmetrics.registerFont(TTFont("DVB", FONT_B))
    cdir = OUT / "certificates"; cdir.mkdir(exist_ok=True)
    for v in VENDORS:
        num, frm, until = CERTIFICATES[v["vendor_id"]]
        fn = cdir / f"{v['vendor_id'].lower()}_iso9001_certificate.pdf"
        c = canvas.Canvas(str(fn), pagesize=A4)
        w, h = A4
        c.setFont("DVB", 22); c.drawCentredString(w / 2, h - 120, "CERTIFICATE OF REGISTRATION")
        c.setFont("DV", 12); c.drawCentredString(w / 2, h - 150, "Fictional Certification Body (FCB) — demo document")
        c.setFont("DV", 12); c.drawCentredString(w / 2, h - 210, "This is to certify that the quality management system of")
        c.setFont("DVB", 18); c.drawCentredString(w / 2, h - 245, v["name"])
        c.setFont("DV", 11); c.drawCentredString(w / 2, h - 268, v["address"])
        c.setFont("DV", 12); c.drawCentredString(w / 2, h - 310, "has been assessed and found to conform to")
        c.setFont("DVB", 16); c.drawCentredString(w / 2, h - 340, "ISO 9001:2015")
        c.setFont("DV", 11)
        c.drawCentredString(w / 2, h - 370, "Scope: Manufacture and supply of corrugated boxes and packaging products")
        c.drawString(90, h - 450, f"Certificate No.: {num}")
        c.drawString(90, h - 470, f"Initial registration: {datetime.fromisoformat(frm):%d %B %Y}")
        c.drawString(90, h - 490, f"Valid until: {datetime.fromisoformat(until):%d %B %Y}")
        c.drawString(90, h - 530, "Validity is subject to satisfactory surveillance audits.")
        c.save()
        GT.setdefault("certificates", {})[v["vendor_id"]] = {"number": num, "valid_until": until}


def main():
    OUT.mkdir(exist_ok=True)
    vendor_a(); vendor_b(); vendor_c(); vendor_d(); vendor_e(); certificates()
    (OUT / "ground_truth.json").write_text(json.dumps(GT, indent=2))
    print("Generated:", *sorted(p.name for p in OUT.iterdir()), sep="\n  ")


if __name__ == "__main__":
    main()
