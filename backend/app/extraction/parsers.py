"""Format-specific parsers. Each turns a file into numbered, locatable Segments.

Segments are the unit of provenance: the model must cite a segment id for every
value, and the evidence viewer jumps to that segment's locator (sheet/row,
page/line/bbox, paragraph, OCR bbox, email line).
"""
from __future__ import annotations

import email
import hashlib
import re
from email import policy
from pathlib import Path
from typing import Optional

from app.domain.extraction import Segment, SourceDocument

ALLOWED_EXT = {".xlsx": "xlsx", ".xls": "xls", ".pdf": "pdf", ".docx": "docx", ".jpg": "image", ".jpeg": "image",
               ".png": "image", ".txt": "text", ".eml": "email"}
MAGIC = {"pdf": b"%PDF", "xlsx": b"PK", "docx": b"PK", "png": b"\x89PNG", "jpg": b"\xff\xd8"}


class UnsupportedDocument(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_format(path: Path, max_mb: float = 25) -> str:
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXT:
        raise UnsupportedDocument(f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXT))}")
    size = path.stat().st_size
    if size == 0:
        raise UnsupportedDocument("File is empty")
    if size > max_mb * 1024 * 1024:
        raise UnsupportedDocument(f"File exceeds {max_mb:.0f} MB limit")
    fmt = ALLOWED_EXT[ext]
    head = path.read_bytes()[:8]
    expect = {"pdf": [MAGIC["pdf"]], "xlsx": [MAGIC["xlsx"]], "docx": [MAGIC["docx"]],
              "image": [MAGIC["png"], MAGIC["jpg"]]}.get(fmt)
    if expect and not any(head.startswith(m) for m in expect):
        raise UnsupportedDocument(f"File content does not match its '{ext}' extension")
    return fmt


def _clean(t: str) -> str:
    return re.sub(r"[ \t]+", " ", (t or "").replace(" ", " ")).strip()


def _seg_factory():
    n = [0]

    def make(text: str, locator: dict, conf: Optional[float] = None) -> Segment:
        n[0] += 1
        return Segment(id=f"S{n[0]:03d}", text=_clean(text), locator=locator, ocr_confidence=conf)
    return make


# ---------------------------------------------------------------- XLSX
def parse_xlsx(path: Path) -> SourceDocument:
    from openpyxl import load_workbook

    make = _seg_factory()
    segs: list[Segment] = []
    warnings: list[str] = []
    wb_v = load_workbook(path, data_only=True)      # cached values
    wb_f = load_workbook(path, data_only=False)     # formulas (for totals the cache may lack)
    for ws in wb_v.worksheets:
        wf = wb_f[ws.title]
        if ws.sheet_state != "visible":
            warnings.append(f"Hidden sheet '{ws.title}' included in extraction")
        for r_idx, row in enumerate(ws.iter_rows(), start=1):
            cells = []
            for c in row:
                v = c.value
                if v is None:
                    fv = wf.cell(row=c.row, column=c.column).value
                    if isinstance(fv, str) and fv.startswith("="):
                        cells.append(f"{c.column_letter}={fv} (formula, value not cached)")
                    continue
                if isinstance(v, float):
                    v = f"{v:.4f}".rstrip("0").rstrip(".")
                cells.append(f"{c.column_letter}={v}")
            if cells:
                segs.append(make(" | ".join(cells), {"kind": "xlsx_row", "sheet": ws.title, "row": r_idx}))
    return SourceDocument(filename=path.name, doc_format="xlsx", sha256=sha256_file(path), segments=segs, warnings=warnings)


# ---------------------------------------------------------------- PDF
def parse_pdf(path: Path) -> SourceDocument:
    import pdfplumber

    make = _seg_factory()
    segs: list[Segment] = []
    warnings: list[str] = []
    with pdfplumber.open(path) as pdf:
        for p_idx, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["size"])
            if not words:
                warnings.append(f"Page {p_idx} has no text layer (scanned?) — needs OCR")
                continue
            # group words into visual lines by 'top' within tolerance
            words.sort(key=lambda w: (round(w["top"] / 3), w["x0"]))
            lines: list[list[dict]] = []
            for w in words:
                if lines and abs(lines[-1][0]["top"] - w["top"]) <= 3:
                    lines[-1].append(w)
                else:
                    lines.append([w])
            for l_idx, ln in enumerate(lines, start=1):
                ln.sort(key=lambda w: w["x0"])
                text, prev = "", None
                for w in ln:
                    gap = (w["x0"] - prev["x1"]) if prev else 0
                    text += ("" if prev is None else (" | " if gap > 12 else " ")) + w["text"]
                    prev = w
                bbox = [min(w["x0"] for w in ln), min(w["top"] for w in ln), max(w["x1"] for w in ln), max(w["bottom"] for w in ln)]
                small = max(w["size"] for w in ln) < 7.5
                loc = {"kind": "pdf_line", "page": p_idx, "line": l_idx, "bbox": [round(b, 1) for b in bbox],
                       "page_size": [round(page.width, 1), round(page.height, 1)]}
                if small:
                    loc["fine_print"] = True
                segs.append(make(text, loc))
    return SourceDocument(filename=path.name, doc_format="pdf", sha256=sha256_file(path), segments=segs, warnings=warnings)


# ---------------------------------------------------------------- DOCX
def parse_docx(path: Path) -> SourceDocument:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    make = _seg_factory()
    segs: list[Segment] = []
    d = Document(str(path))
    p_idx = t_idx = 0
    for block in d.element.body.iterchildren():
        tag = block.tag.split("}")[-1]
        if tag == "p":
            p_idx += 1
            para = Paragraph(block, d)
            if para.text.strip():
                # split long paragraphs into sentences so citations stay precise
                t = para.text.strip()
                parts = re.split(r"(?<=[a-z0-9)]{3}[.;])\s+(?=[A-Z])", t) if len(t) > 200 else [t]
                for s_i, part in enumerate(parts, start=1):
                    segs.append(make(part, {"kind": "docx_paragraph", "paragraph": p_idx, "sentence": s_i}))
        elif tag == "tbl":
            t_idx += 1
            tbl = Table(block, d)
            for r_i, row in enumerate(tbl.rows, start=1):
                vals = []
                for c in row.cells:
                    t = c.text.strip()
                    if not vals or vals[-1] != t:  # merged cells repeat text
                        vals.append(t)
                segs.append(make(" | ".join(vals), {"kind": "docx_table_row", "table": t_idx, "row": r_i}))
    for sec in d.sections:
        for p in sec.footer.paragraphs:
            if p.text.strip():
                segs.append(make(p.text, {"kind": "docx_footer"}))
    return SourceDocument(filename=path.name, doc_format="docx", sha256=sha256_file(path), segments=segs)


# ---------------------------------------------------------------- Image
def parse_image(path: Path, derived_dir: Optional[Path] = None) -> SourceDocument:
    import cv2

    from app.extraction.image_prep import ocr_lines, prepare

    make = _seg_factory()
    prepared, gray = prepare(path)
    lines = ocr_lines(gray)
    segs = [make(l["text"], {"kind": "ocr_line", "line": i, "bbox": l["bbox"]}, conf=round(l["conf"], 1))
            for i, l in enumerate(lines, start=1)]
    warnings = list(prepared.notes)
    if segs:
        mean = sum(s.ocr_confidence or 0 for s in segs) / len(segs)
        low = sum(1 for s in segs if (s.ocr_confidence or 0) < 60)
        warnings.append(f"OCR mean confidence {mean:.0f}/100; {low} low-confidence line(s)")
    else:
        warnings.append("OCR found no text")
    derived = None
    if derived_dir:
        derived_dir.mkdir(parents=True, exist_ok=True)
        derived = derived_dir / f"{path.stem}.corrected.png"
        cv2.imwrite(str(derived), gray)
    return SourceDocument(filename=path.name, doc_format="image", sha256=sha256_file(path), segments=segs,
                          warnings=warnings, derived_image_path=str(derived) if derived else None,
                          meta={"height": int(gray.shape[0]), "width": int(gray.shape[1])})


# ---------------------------------------------------------------- Email / text
def parse_email(path: Path) -> SourceDocument:
    make = _seg_factory()
    raw = path.read_bytes()
    msg = email.message_from_bytes(raw, policy=policy.default)
    meta = {k.lower(): str(msg.get(k, "")) for k in ("From", "To", "Subject", "Date")}
    segs = [make(f"{k.title()}: {v}", {"kind": "email_header", "header": k}) for k, v in meta.items() if v]
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body is not None and body.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    quoted = False
    for i, line in enumerate(text.splitlines(), start=1):
        if re.match(r"^-{3,}\s*Original Message", line) or line.startswith(">"):
            quoted = True
        if line.strip():
            loc = {"kind": "email_line", "line": i}
            if quoted:
                loc["quoted_history"] = True
            segs.append(make(line, loc))
    attachments = [p.get_filename() for p in msg.iter_attachments()]
    meta["attachments"] = attachments
    return SourceDocument(filename=path.name, doc_format="email", sha256=sha256_file(path), segments=segs, meta=meta)


def parse_text(path: Path) -> SourceDocument:
    make = _seg_factory()
    text = path.read_text(errors="replace")
    segs = [make(l, {"kind": "text_line", "line": i}) for i, l in enumerate(text.splitlines(), start=1) if l.strip()]
    return SourceDocument(filename=path.name, doc_format="text", sha256=sha256_file(path), segments=segs)


def parse_document(path: str | Path, derived_dir: Optional[Path] = None, max_mb: float = 25) -> SourceDocument:
    path = Path(path)
    fmt = detect_format(path, max_mb)
    if fmt == "xlsx":
        return parse_xlsx(path)
    if fmt == "xls":
        raise UnsupportedDocument("Legacy .xls is accepted for upload but must be re-saved as .xlsx (no xlrd in this build)")
    if fmt == "pdf":
        doc = parse_pdf(path)
        if not doc.segments:
            raise UnsupportedDocument("PDF has no text layer; scanned PDFs need OCR (not implemented in this build)")
        return doc
    if fmt == "docx":
        return parse_docx(path)
    if fmt == "image":
        return parse_image(path, derived_dir)
    if fmt == "email":
        return parse_email(path)
    return parse_text(path)
