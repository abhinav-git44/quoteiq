"""Exports built from persisted/normalized data only (never from model prose)."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.analyst.context import AnalysisContext
from app.optimization.award import Scenario

GREEN = PatternFill("solid", fgColor="D9F2E3")
AMBER = PatternFill("solid", fgColor="FFF1CC")
GREY = PatternFill("solid", fgColor="EEEEEE")
RED = PatternFill("solid", fgColor="FADBD8")
HEAD = PatternFill("solid", fgColor="1E2A4A")
WHITE_B = Font(bold=True, color="FFFFFF")


def _header(ws, cols, row=1):
    for i, c in enumerate(cols, start=1):
        cell = ws.cell(row=row, column=i, value=c)
        cell.font, cell.fill = WHITE_B, HEAD
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = ws.cell(row=row + 1, column=3)


def _widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def comparison_xlsx(ctx: AnalysisContext, path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Comparison (normalized)"
    vids = [v["vendor_id"] for v in ctx.vendors]
    names = ctx.names
    ws["A1"] = f"{ctx.rfx['reference']} — {ctx.rfx['title']}"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = (f"Unit prices in {ctx.settings.base_currency} per RFx unit, ex-GST, after unconditional discounts. "
                "Green = lowest comparable; amber = awaiting verification; grey = not quoted / not comparable. "
                "SYNTHETIC DEMO DATA.")
    cols = ["Line", "Item", "Qty", "UOM", "Target ₹"] + [f"{names[v]} ({ctx.eligibility[v].status if v in ctx.eligibility else '?'})" for v in vids] + ["Lowest (all)", "Lowest eligible"]
    _header(ws, cols, row=4)
    for r, l in enumerate(ctx.lines, start=5):
        ws.cell(row=r, column=1, value=l["line_id"]); ws.cell(row=r, column=2, value=l["name"])
        ws.cell(row=r, column=3, value=l["quantity"]); ws.cell(row=r, column=4, value=l["uom"])
        ws.cell(row=r, column=5, value=l.get("target_price_inr"))
        qs = {v: ctx.norm.get(v, l["line_id"]) for v in vids}
        comp = {v: q.unit_price_base for v, q in qs.items() if q and q.comparable}
        low = min(comp, key=comp.get) if comp else None
        el = {v: p for v, p in comp.items() if ctx.eligibility.get(v) and ctx.eligibility[v].status == "ELIGIBLE"}
        low_e = min(el, key=el.get) if el else None
        for i, v in enumerate(vids):
            q = qs[v]
            c = ws.cell(row=r, column=6 + i)
            if q and q.comparable:
                c.value = round(q.unit_price_base, 4)
                c.number_format = "#,##0.00"
                c.fill = AMBER if q.review_required else (GREEN if v == low else PatternFill())
                note = " → ".join(s.detail for s in q.trace[:5])
                if q.evidence.segment_id:
                    note += f"\nSource: {q.evidence.filename} {q.evidence.segment_id}: {(q.evidence.text or '')[:120]}"
                c.comment = Comment(note[:1000], "QuoteIQ")
            else:
                c.value = (q.status if q else "NOT_QUOTED").replace("_", " ").title()
                c.fill = GREY
                if q and q.reason:
                    c.comment = Comment(q.reason[:500], "QuoteIQ")
        ws.cell(row=r, column=6 + len(vids), value=names.get(low) if low else "—")
        ws.cell(row=r, column=7 + len(vids), value=names.get(low_e) if low_e else "—")
    _widths(ws, [6, 42, 10, 6, 10] + [18] * len(vids) + [20, 20])

    ws2 = wb.create_sheet("Original quotes")
    _header(ws2, ["Vendor", "Line", "Status", "Quoted price", "Currency", "Basis", "Conversion", "Confidence", "Needs verification",
                  "Source file", "Segment", "Source text"])
    r = 2
    for q in ctx.norm.quotes:
        ws2.append([names[q.vendor_id], q.rfx_line_id, q.status, q.original_price, q.original_currency, q.price_basis_text,
                    q.conversion_kind, round(q.confidence), "YES" if q.review_required else "", q.evidence.filename,
                    q.evidence.segment_id, (q.evidence.text or "")[:200]])
        r += 1
    _widths(ws2, [22, 6, 18, 12, 9, 16, 16, 10, 10, 30, 8, 60])

    ws3 = wb.create_sheet("Coverage & terms")
    _header(ws3, ["Vendor", "Quoted", "Comparable", "Not quoted", "Needs clarification", "Not comparable", "Unreadable",
                  "Freight", "Freight note", "Tax", "Payment days", "Delivery days", "Conditional discounts", "Quality"])
    for vs in ctx.norm.vendors:
        cc = vs.coverage_counts
        ws3.append([vs.vendor_name, vs.quoted_lines, vs.comparable_lines, cc.get("NOT_QUOTED", 0), cc.get("NEEDS_CLARIFICATION", 0),
                    cc.get("NOT_COMPARABLE", 0), cc.get("UNREADABLE", 0), vs.freight_basis, vs.freight_note, vs.tax_basis,
                    vs.payment_days, f"{vs.delivery_days_min or ''}-{vs.delivery_days_max or ''}",
                    "; ".join(f"{d.get('value')}% {d.get('condition_text') or d.get('condition_type')}" for d in vs.conditional_discounts),
                    ctx.eligibility[vs.vendor_id].status if vs.vendor_id in ctx.eligibility else ""])
    _widths(ws3, [22, 8, 10, 10, 12, 12, 10, 18, 50, 10, 10, 10, 50, 12])

    ws4 = wb.create_sheet("Assumptions & policy")
    ws4.append(["Item", "Value"])
    for k, v in ctx.norm.policy.items():
        ws4.append([k, str(v)])
    for r_ in ctx.fx_rates:
        ws4.append([f"FX {r_['from_currency']}→{r_['to_currency']}", f"{r_['rate']} ({r_['source']}, {r_['rate_date']})"])
    ws4.append(["Weight model", "Per-kg prices converted with blank area × board GSM from RFx specs (see trace comments)"])
    ws4.append(["Generated", datetime.now().isoformat(timespec="seconds")])
    _widths(ws4, [36, 100])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def exceptions_xlsx(ctx: AnalysisContext, path: Path) -> Path:
    from app.analyst.tools import ExceptionArgs, get_extraction_exceptions

    out = get_extraction_exceptions(ctx, ExceptionArgs())
    wb = Workbook()
    ws = wb.active
    ws.title = "Exceptions"
    d = out["displays"][0]
    _header(ws, d["columns"])
    for row in d["rows"]:
        ws.append(row)
    _widths(ws, [22, 6, 20, 10, 80, 30])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ------------------------------------------------------------------ PDF
def _fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for reg, bold in [("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                      ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
                      ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf")]:
        if Path(reg).exists() and Path(bold).exists():
            try:
                pdfmetrics.registerFont(TTFont("QI", reg)); pdfmetrics.registerFont(TTFont("QIB", bold))
                return "QI", "QIB", "₹"
            except Exception:
                pass
    return "Helvetica", "Helvetica-Bold", "Rs."


def _money(x, sym):
    if x is None:
        return "—"
    neg = x < 0
    x = abs(x)
    whole, frac = f"{x:.0f}", ""
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    return f"{'-' if neg else ''}{sym}{whole}{frac}"


def award_pdf(ctx: AnalysisContext, scenario: Scenario, path: Path, baseline: Optional[Scenario] = None,
              approval: Optional[dict[str, Any]] = None) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from app.optimization.award import compare_savings

    F, FB, SYM = _fonts()
    N = ParagraphStyle("n", fontName=F, fontSize=8.5, leading=11)
    S = ParagraphStyle("s", fontName=F, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#444444"))
    H1 = ParagraphStyle("h1", fontName=FB, fontSize=15, leading=19, textColor=colors.HexColor("#1E2A4A"))
    H2 = ParagraphStyle("h2", fontName=FB, fontSize=10.5, leading=14, spaceBefore=8, textColor=colors.HexColor("#1E2A4A"))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Award recommendation {ctx.rfx['reference']}")
    st = [Paragraph(f"Award recommendation — {ctx.rfx['reference']}", H1),
          Paragraph(f"{ctx.rfx['title']} · Scenario <b>{scenario.name}</b> ({scenario.scenario_id}) · {scenario.cost_basis_label} · "
                    f"generated {datetime.now():%d %b %Y %H:%M} · SYNTHETIC DEMO DATA", S), Spacer(1, 4 * mm)]
    status = "APPROVED" if approval else "PENDING HUMAN APPROVAL"
    summary = [["Net total", _money(scenario.net_total, SYM)], ["Gross (before conditional discounts)", _money(scenario.gross_total, SYM)],
               ["Lines allocated / unallocated", f"{scenario.lines_allocated} / {scenario.lines_unallocated}"],
               ["Vendors used", ", ".join(f"{v['vendor_name']} {v['pct']}%" for v in scenario.vendor_shares)],
               ["Target (last-contract) value of allocated lines", _money(scenario.target_total_allocated, SYM)],
               ["Status", status + (f" — {approval.get('approved_by')} on {approval.get('approved_at')}" if approval else "")]]
    if baseline:
        cmp = compare_savings(scenario, baseline)
        summary.insert(2, [f"Savings vs {baseline.name} (like-for-like, {cmp['common_lines']} lines)",
                           f"{_money(cmp['savings'], SYM)} ({cmp['savings_pct']}%)"])
    t = Table(summary, colWidths=[95 * mm, 160 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 9), ("FONT", (0, 0), (0, -1), FB, 9),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F4FA"))]))
    st += [t]
    if scenario.discounts_applied:
        st.append(Paragraph("Conditional discounts", H2))
        for d in scenario.discounts_applied:
            st.append(Paragraph(f"{d['vendor_name']}: {d['pct']}% if {d['condition']} — "
                                f"{'APPLIED ' + _money(d['amount'], SYM) if d['applied'] else 'not earned'} ({d['why']})", N))
    st.append(Paragraph("Risks", H2))
    for r in scenario.risks or ["None identified by rules"]:
        st.append(Paragraph("• " + r, N))
    st.append(Paragraph("Assumptions", H2))
    for a in scenario.assumptions:
        st.append(Paragraph("• " + a, N))
    if scenario.excluded_vendors:
        st.append(Paragraph("Vendors excluded from this scenario", H2))
        for e in scenario.excluded_vendors:
            st.append(Paragraph(f"• {ctx.names.get(e['vendor_id'], e['vendor_id'])}: {e['reason']}", N))
    st += [PageBreak(), Paragraph("Line allocation", H2)]
    rows = [["Line", "Item", "Vendor", "Qty", "Unit", "Value", "Runner-up", "R-up unit", "Conf.", "Verify"]]
    for a in scenario.allocations:
        rows.append([a.line_id, Paragraph(a.line_name, S), a.vendor_name, f"{a.quantity:,.0f}", f"{a.unit_price:,.2f}",
                     _money(a.value, SYM), ctx.names.get(a.runner_up_vendor_id, "—"),
                     f"{a.runner_up_unit_price:,.2f}" if a.runner_up_unit_price else "—", f"{a.confidence:.0f}",
                     "YES" if a.review_required else ""])
    for u in scenario.unallocated:
        rows.append([u["line_id"], Paragraph(u["line_name"], S), "UNALLOCATED", f"{u['quantity']:,}", "", "", "", "", "",
                     Paragraph(u["reason"][:120], S)])
    t2 = Table(rows, colWidths=[12 * mm, 70 * mm, 38 * mm, 20 * mm, 18 * mm, 28 * mm, 34 * mm, 18 * mm, 12 * mm, 20 * mm], repeatRows=1)
    style = [("FONT", (0, 0), (-1, -1), F, 7.5), ("FONT", (0, 0), (-1, 0), FB, 7.5),
             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E2A4A")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("ALIGN", (3, 1), (5, -1), "RIGHT")]
    for i, a in enumerate(scenario.allocations, start=1):
        if a.review_required:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FFF1CC")))
    t2.setStyle(TableStyle(style))
    st += [t2, Spacer(1, 6 * mm),
           Paragraph("Every unit price is traceable to a source document segment and a calculation trace in QuoteIQ. "
                     "Award authority rests with the buyer; this document is a recommendation.", S)]
    doc.build(st)
    return path


def quality_pdf(ctx: AnalysisContext, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    F, FB, _ = _fonts()
    N = ParagraphStyle("n", fontName=F, fontSize=8, leading=10)
    H = ParagraphStyle("h", fontName=FB, fontSize=11, leading=14, spaceBefore=6)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm)
    st = [Paragraph(f"Quality questionnaire evaluation — {ctx.rfx['reference']}", ParagraphStyle("t", fontName=FB, fontSize=14, leading=18)),
          Paragraph("Policy: eligible only if every mandatory question passes; missing mandatory answers remain PENDING. "
                    "SYNTHETIC DEMO DATA.", N), Spacer(1, 3 * mm)]
    colour = {"PASS": "#D9F2E3", "FAIL": "#FADBD8", "PENDING": "#FFF1CC", "NEEDS_REVIEW": "#FFF1CC"}
    for v in ctx.vendors:
        e = ctx.eligibility.get(v["vendor_id"])
        if not e:
            continue
        st.append(Paragraph(f"{v['name']} — {e.status} (score {e.quality_score})", H))
        rows = [["Q", "Mand.", "Answer", "Status", "Reason"]]
        style = [("FONT", (0, 0), (-1, -1), F, 7.5), ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                 ("FONT", (0, 0), (-1, 0), FB, 7.5)]
        for i, a in enumerate(e.answers, start=1):
            rows.append([a.qid, "Y" if a.mandatory else "", str(a.answer), a.status, Paragraph(a.reason, N)])
            if a.status in colour:
                style.append(("BACKGROUND", (3, i), (3, i), colors.HexColor(colour[a.status])))
        t = Table(rows, colWidths=[12 * mm, 12 * mm, 18 * mm, 24 * mm, 116 * mm])
        t.setStyle(TableStyle(style))
        st.append(t)
    doc.build(st)
    return path


def audit_csv(events: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["event_id", "timestamp", "user", "action", "entity_type", "entity_id", "document_id", "before", "after", "metadata"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for e in events:
            w.writerow({k: e.get(k) for k in cols})
    return path
