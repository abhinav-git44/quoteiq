"""Assemble an AnalysisContext from extraction outcomes + questionnaire evidence.

Used by the API (from DB rows), by scripts/run_pipeline.py (from files) and by tests.
"""
from __future__ import annotations

from typing import Any, Optional

from app.analyst.context import AnalysisContext
from app.core.config import Settings, get_settings
from app.domain.extraction import ExtractionOutcome
from app.normalization.adapter import outcome_to_vendor_input
from app.quality.eligibility import evaluate_vendor


def build_context(*, rfx: dict, lines: list[dict], vendors: list[dict], questionnaire: list[dict],
                  answers: dict[str, dict], cert_evidence: dict[str, dict], outcomes: dict[str, ExtractionOutcome],
                  fx_rates: list[dict], corrections: Optional[dict[str, dict]] = None,
                  qa_overrides: Optional[dict[str, dict]] = None, document_ids: Optional[dict[str, str]] = None,
                  settings: Settings | None = None, **kw: Any) -> AnalysisContext:
    s = settings or get_settings()
    corrections = corrections or {}
    names = {v["vendor_id"]: v["name"] for v in vendors}
    inputs, extraction = [], {}
    for vid in names:
        oc = outcomes.get(vid)
        if oc is None:
            extraction[vid] = {"status": "NOT_SUBMITTED", "exceptions": []}
            continue
        inputs.append(outcome_to_vendor_input(oc, vid, names[vid], (document_ids or {}).get(vid), corrections.get(vid)))
        extraction[vid] = {"status": oc.status, "filename": oc.document.filename if oc.document else None,
                           "document_id": (document_ids or {}).get(vid), "error": oc.error,
                           "exceptions": [e.model_dump() for e in oc.exceptions]}
    elig = {}
    for vid in names:
        ev = {}
        ce = cert_evidence.get(vid)
        if ce:
            ev["iso9001_certificate"] = ce
        elig[vid] = evaluate_vendor(vid, questionnaire, answers.get(vid, {}), ev, rfx["issue_date"],
                                    (qa_overrides or {}).get(vid), s.confidence_review)
    return AnalysisContext(rfx=rfx, lines=lines, vendors=vendors, questionnaire=questionnaire, vendor_inputs=inputs,
                           fx_rates=fx_rates, eligibility=elig, extraction=extraction, settings=s, **kw)
