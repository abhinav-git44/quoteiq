"""Document -> validated quotation.

parse (deterministic) -> Claude extraction via forced tool call (schema-validated, retried
with the validation errors) -> grounding checks (deterministic) -> coverage + exceptions.
If no API key is configured the pipeline stops after parsing with AI_UNAVAILABLE; it never
substitutes values from anywhere else.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from app.ai.llm import LLMClient, LLMError, image_block, inline_schema, tool_uses
from app.ai.prompts import CERTIFICATE_SYSTEM, EXTRACTION_SYSTEM
from app.core.config import Settings, get_settings
from app.domain.extraction import (Check, ExceptionItem, ExtractionOutcome, LLMCertificate, LLMQuotation,
                                   SourceDocument, ValidatedField, ValidatedLine)
from app.extraction import grounding as G
from app.extraction.parsers import UnsupportedDocument, parse_document

log = logging.getLogger("quoteiq.extraction")
SUPPORTED_CCY = {"INR", "USD", "EUR", "GBP"}
MAX_ATTEMPTS = 3


def rfx_lines_prompt(rfx_lines: list[dict]) -> str:
    rows = []
    for l in rfx_lines:
        s = l["spec"]
        dims = "×".join(str(int(d)) for d in (s.get("length_mm"), s.get("width_mm"), s.get("height_mm")) if d)
        bits = [l["line_id"], l["name"], f"{dims} mm" if dims else "", f"{s['ply']}-ply" if s.get("ply") else "",
                f"board {s['board_gsm']} gsm" if s.get("board_gsm") else "",
                f"BS≥{s['bursting_strength_kg_cm2']}" if s.get("bursting_strength_kg_cm2") else "",
                f"qty {l['quantity']} {l['uom']}"]
        rows.append(" | ".join(b for b in bits if b))
    return "\n".join(rows)


def _call_tool(llm: LLMClient, system: str, content: list[dict], tool_name: str, model_cls, description: str,
               max_tokens: int) -> tuple[object, dict, int]:
    tool = {"name": tool_name, "description": description, "input_schema": inline_schema(model_cls.model_json_schema())}
    messages: list[dict] = [{"role": "user", "content": content}]
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        resp = llm.create(system=system, messages=messages, tools=[tool],
                          tool_choice={"type": "tool", "name": tool_name}, max_tokens=max_tokens)
        uses = [u for u in tool_uses(resp) if u.get("name") == tool_name]
        if not uses:
            last_err = "Model did not call the extraction tool"
            messages += [{"role": "assistant", "content": resp.get("content", [])},
                         {"role": "user", "content": f"You must call {tool_name}."}]
            continue
        use = uses[0]
        try:
            return model_cls.model_validate(use["input"]), use["input"], attempt
        except ValidationError as e:
            last_err = e.errors(include_url=False)
            log.warning("Extraction schema validation failed (attempt %d): %d errors", attempt, len(last_err))
            messages += [{"role": "assistant", "content": resp["content"]},
                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": use["id"], "is_error": True,
                                                       "content": "Schema validation failed; fix and call again:\n"
                                                                  + json.dumps(last_err, default=str)[:4000]}]}]
        if resp.get("stop_reason") == "max_tokens":
            last_err = "Model output truncated (max_tokens)"
    raise LLMError(f"Extraction failed validation after {MAX_ATTEMPTS} attempts: {str(last_err)[:500]}")


# ------------------------------------------------------------------ validation
def _field(doc, name, tv, numeric=False) -> ValidatedField:
    if tv is None:
        return ValidatedField(name=name, value=None)
    val = getattr(tv, "value", None)
    checks, seg = G.citation_checks(doc, tv.segment_id, tv.snippet, val if (numeric and val is not None) else None)
    if val is None:
        checks = [Check(name="present", passed=None, detail="Not stated in document")]
    conf = G.score(checks)
    return ValidatedField(name=name, value=val, segment_id=seg.id if seg else tv.segment_id, snippet=tv.snippet,
                          checks=checks, confidence=conf, review_required=val is not None and conf < 70)


def validate_quotation(doc: SourceDocument, q: LLMQuotation, rfx_lines: list[dict],
                       settings: Settings | None = None) -> tuple[list[ValidatedField], list[ValidatedLine], dict, list[ExceptionItem]]:
    s = settings or get_settings()
    by_id = {l["line_id"]: l for l in rfx_lines}
    exc: list[ExceptionItem] = []
    h = q.header
    fields = [
        _field(doc, "vendor_name", h.vendor_name), _field(doc, "quotation_ref", h.quotation_ref),
        _field(doc, "quotation_date", h.quotation_date), _field(doc, "currency", h.currency),
        _field(doc, "validity_days", h.validity_days, True), _field(doc, "payment_terms_text", h.payment_terms_text),
        _field(doc, "payment_days", h.payment_days, True), _field(doc, "delivery_days_min", h.delivery_days_min, True),
        _field(doc, "delivery_days_max", h.delivery_days_max, True),
    ]
    fr_checks = (G.citation_checks(doc, h.freight.segment_id, h.freight.snippet,
                                   h.freight.amount if h.freight.basis not in ("INCLUDED", "EXTRA_AT_ACTUALS") else None)[0]
                 if h.freight.basis != "UNSPECIFIED" else [Check(name="present", passed=None, detail="Freight terms not stated")])
    fields.append(ValidatedField(name="freight", value=h.freight.model_dump(exclude={"segment_id", "snippet"}),
                                 segment_id=h.freight.segment_id, snippet=h.freight.snippet, checks=fr_checks,
                                 confidence=G.score(fr_checks), review_required=G.score(fr_checks) < s.confidence_review))
    tx_checks = (G.citation_checks(doc, h.tax.segment_id, h.tax.snippet, h.tax.rate_pct)[0] if h.tax.basis != "UNSPECIFIED"
                 else [Check(name="present", passed=None, detail="Tax treatment not stated")])
    fields.append(ValidatedField(name="tax", value=h.tax.model_dump(exclude={"segment_id", "snippet"}),
                                 segment_id=h.tax.segment_id, snippet=h.tax.snippet, checks=tx_checks,
                                 confidence=G.score(tx_checks), review_required=G.score(tx_checks) < s.confidence_review))
    ccy = (h.currency.value or "").upper().strip() or None
    if not ccy:
        exc.append(ExceptionItem(code="CURRENCY_UNKNOWN", severity="BLOCKING",
                                 message="Quoted currency not stated; prices cannot be normalised until confirmed."))
    elif ccy not in SUPPORTED_CCY:
        exc.append(ExceptionItem(code="CURRENCY_UNSUPPORTED", severity="BLOCKING", message=f"Currency {ccy} has no configured rate"))
    if h.freight.basis == "UNSPECIFIED":
        exc.append(ExceptionItem(code="FREIGHT_UNSPECIFIED", severity="WARNING",
                                 message="Freight terms not stated — landed cost cannot be confirmed."))
    if h.freight.basis == "EXTRA_AT_ACTUALS":
        exc.append(ExceptionItem(code="FREIGHT_AT_ACTUALS", severity="WARNING",
                                 message="Freight 'at actuals' — landed cost uses a configurable assumption until confirmed.",
                                 segment_id=h.freight.segment_id))
    if h.tax.basis == "UNSPECIFIED":
        exc.append(ExceptionItem(code="TAX_UNSPECIFIED", severity="INFO", message="Tax treatment not stated; assumed ex-GST."))
    for w in q.document_warnings:
        exc.append(ExceptionItem(code="DOCUMENT_WARNING", severity="WARNING", message=w))

    vlines: list[ValidatedLine] = []
    for ln in q.line_items:
        if ln.rfx_line_id and ln.rfx_line_id not in by_id:
            exc.append(ExceptionItem(code="UNKNOWN_RFX_LINE", severity="WARNING",
                                     message=f"Model matched to unknown line {ln.rfx_line_id}; treated as unmatched",
                                     segment_id=ln.segment_id))
            ln = ln.model_copy(update={"rfx_line_id": None})
        checks, seg = G.line_checks(doc, by_id.get(ln.rfx_line_id), ln)
        if ln.price is not None and ln.price <= 0:
            checks.append(Check(name="price_positive", passed=False, detail="Non-positive price", penalty=60))
        line_ccy = (ln.price_currency or ccy or "").upper()
        if line_ccy and ccy and line_ccy != ccy:
            checks.append(Check(name="currency_consistency", passed=None, detail=f"Line currency {line_ccy} differs from header {ccy}"))
        conf = G.score(checks)
        vlines.append(ValidatedLine(llm=ln, checks=checks, confidence=conf,
                                    band=G.band(conf, s.confidence_high, s.confidence_review),
                                    review_required=conf < s.confidence_review or ln.price is None,
                                    evidence_locator=seg.locator if seg else None, evidence_text=seg.text if seg else None))
        if ln.rfx_line_id is None:
            exc.append(ExceptionItem(code="UNMATCHED_VENDOR_LINE", severity="WARNING",
                                     message=f"Vendor line '{ln.vendor_description[:60]}' not matched to any RFx line",
                                     segment_id=ln.segment_id))

    # duplicates: keep the highest-confidence line per RFx line as primary, flag the rest
    by_rfx: dict[str, list[ValidatedLine]] = {}
    for v in vlines:
        if v.llm.rfx_line_id:
            by_rfx.setdefault(v.llm.rfx_line_id, []).append(v)
    for lid, group in by_rfx.items():
        if len(group) > 1:
            group.sort(key=lambda v: -v.confidence)
            for extra in group[1:]:
                extra.checks.append(Check(name="duplicate_match", passed=False,
                                          detail=f"Another vendor line also matched {lid}", penalty=G.PENALTY["duplicate"]))
                extra.confidence = G.score(extra.checks)
                extra.band = G.band(extra.confidence, s.confidence_high, s.confidence_review)
                extra.review_required = True
            exc.append(ExceptionItem(code="DUPLICATE_MATCH", severity="WARNING", rfx_line_id=lid,
                                     message=f"{len(group)} vendor lines matched {lid}; highest-confidence one used"))

    coverage: dict[str, str] = {}
    unresolved = {lid for u in q.unresolved_references for lid in u.rfx_line_ids}
    for lid in by_id:
        primary = by_rfx.get(lid, [None])[0]
        if primary is not None:
            coverage[lid] = "QUOTED" if primary.llm.price is not None else "UNREADABLE"
        elif lid in unresolved:
            coverage[lid] = "NEEDS_CLARIFICATION"
        else:
            coverage[lid] = "NOT_QUOTED"
    for u in q.unresolved_references:
        exc.append(ExceptionItem(code="UNRESOLVED_REFERENCE", severity="BLOCKING", segment_id=u.segment_id,
                                 message=f"“{u.text[:120]}” — {u.reason}. Affects {len(u.rfx_line_ids)} line(s); "
                                         "clarification needed from vendor."))
    for v in vlines:
        if v.llm.rfx_line_id and v.llm.price is None:
            exc.append(ExceptionItem(code="UNREADABLE_PRICE", severity="BLOCKING", rfx_line_id=v.llm.rfx_line_id,
                                     segment_id=v.llm.segment_id, message="Price present but not legible"))
        elif v.review_required and v.llm.rfx_line_id:
            worst = sorted([c for c in v.checks if c.penalty], key=lambda c: -c.penalty)[:2]
            exc.append(ExceptionItem(code="LOW_CONFIDENCE", severity="WARNING", rfx_line_id=v.llm.rfx_line_id,
                                     segment_id=v.llm.segment_id,
                                     message=f"Confidence {v.confidence:.0f}: " + "; ".join(c.detail for c in worst)))
    return fields, vlines, coverage, exc


def extract_quotation(path: str | Path, rfx_lines: list[dict], llm: Optional[LLMClient],
                      settings: Settings | None = None, derived_dir: Optional[Path] = None,
                      vendor_hint: Optional[str] = None) -> ExtractionOutcome:
    s = settings or get_settings()
    if derived_dir is None:
        import tempfile
        derived_dir = Path(tempfile.mkdtemp(prefix="quoteiq-derived-"))
    try:
        doc = parse_document(path, derived_dir=derived_dir, max_mb=s.max_upload_mb)
    except UnsupportedDocument as e:
        return ExtractionOutcome(status="FAILED", error=str(e))
    except Exception as e:  # corrupt files etc.
        log.exception("Parser failed")
        return ExtractionOutcome(status="FAILED", error=f"Could not read document: {e.__class__.__name__}")
    if not doc.segments:
        return ExtractionOutcome(status="FAILED", document=doc, error="No readable text found in document")
    if llm is None:
        return ExtractionOutcome(status="AI_UNAVAILABLE", document=doc,
                                 error="AI extraction unavailable: ANTHROPIC_API_KEY not configured. "
                                       "Parsed text is shown; no values were extracted.")
    content: list[dict] = []
    if doc.doc_format == "image" and doc.derived_image_path:
        content.append(image_block(doc.derived_image_path))
    content.append({"type": "text", "text":
                    f"RFx lines (match vendor lines to these ids):\n{rfx_lines_prompt(rfx_lines)}\n\n"
                    + (f"Expected vendor (from submission record, verify against document): {vendor_hint}\n\n" if vendor_hint else "")
                    + f'<vendor_document format="{doc.doc_format}" filename="{doc.filename}">\n'
                    + doc.as_prompt_text() + "\n</vendor_document>"})
    try:
        q, raw, attempts = _call_tool(llm, EXTRACTION_SYSTEM, content, "record_quotation", LLMQuotation,
                                      "Record the vendor's quotation against the RFx.", max_tokens=16000)
    except LLMError as e:
        return ExtractionOutcome(status="FAILED", document=doc, error=str(e), model=getattr(llm, "model", None))
    fields, vlines, coverage, exc = validate_quotation(doc, q, rfx_lines, s)
    needs_review = any(v.review_required for v in vlines) or any(f.review_required for f in fields) \
        or any(e.severity == "BLOCKING" for e in exc)
    status = "NEEDS_REVIEW" if needs_review else "SUCCEEDED"
    if not vlines and not q.unresolved_references:
        status = "FAILED"
        exc.append(ExceptionItem(code="NO_LINES", severity="BLOCKING", message="No priced lines found"))
    return ExtractionOutcome(status=status, document=doc, raw_llm=raw, quotation=q, header_fields=fields, lines=vlines,
                             coverage=coverage, exceptions=exc, model=getattr(llm, "model", None), attempts=attempts)


def extract_certificate(path: str | Path, llm: Optional[LLMClient], settings: Settings | None = None) -> dict:
    """Read an ISO certificate with the model; deterministic grounding of the expiry date."""
    s = settings or get_settings()
    doc = parse_document(path, max_mb=s.max_upload_mb)
    if llm is None:
        return {"status": "AI_UNAVAILABLE", "document": doc}
    content = [{"type": "text", "text": f'<vendor_document format="{doc.doc_format}">\n{doc.as_prompt_text()}\n</vendor_document>'}]
    cert, raw, _ = _call_tool(llm, CERTIFICATE_SYSTEM, content, "record_certificate", LLMCertificate,
                              "Record the certificate fields.", max_tokens=2000)
    checks, seg = G.citation_checks(doc, cert.valid_until.segment_id, cert.valid_until.snippet)
    return {"status": "SUCCEEDED", "document": doc, "certificate": cert, "valid_until_checks": checks,
            "valid_until_confidence": G.score(checks)}
