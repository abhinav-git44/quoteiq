import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from app.analyst.builder import build_context  # noqa: E402
from app.demo.catalog import (CERTIFICATES, EXCHANGE_RATES, QUESTIONNAIRE, QUESTIONNAIRE_ANSWERS, RFX, VENDORS,  # noqa: E402
                              rfx_line_items)
from app.domain.extraction import ExtractionOutcome, LLMQuotation  # noqa: E402
from app.extraction.parsers import parse_document  # noqa: E402
from app.extraction.pipeline import validate_quotation  # noqa: E402
from sim_extraction import DEMO, FILES, simulated_quotation  # noqa: E402

_DOCS = {}


def parsed(vid):
    if vid not in _DOCS:
        _DOCS[vid] = parse_document(DEMO / FILES[vid], derived_dir=Path("/tmp/quoteiq-test-derived"))
    return _DOCS[vid]


def sim_outcome(vid, perturb=None):
    doc = parsed(vid)
    q = LLMQuotation.model_validate(simulated_quotation(vid, doc, perturb))
    fields, lines, cov, exc = validate_quotation(doc, q, rfx_line_items())
    return ExtractionOutcome(status="NEEDS_REVIEW", document=doc, quotation=q, header_fields=fields, lines=lines,
                             coverage=cov, exceptions=exc, model="simulated")


def cert_evidence():
    return {vid: {"status": "SUCCEEDED", "valid_until": until, "number": num, "confidence": 100}
            for vid, (num, _, until) in CERTIFICATES.items()}


@pytest.fixture(scope="session")
def outcomes():
    return {vid: sim_outcome(vid) for vid in FILES}


@pytest.fixture()
def ctx(outcomes, tmp_path):
    exported = {}

    def exporter(kind, params):
        from app.reporting import exports as X
        p = tmp_path / f"{kind}.{ 'pdf' if kind.endswith('pdf') else ('csv' if kind.endswith('csv') else 'xlsx')}"
        if kind == "comparison_xlsx":
            X.comparison_xlsx(c, p)
        elif kind == "exceptions_xlsx":
            X.exceptions_xlsx(c, p)
        elif kind == "quality_pdf":
            X.quality_pdf(c, p)
        elif kind == "award_pdf":
            X.award_pdf(c, c.scenarios[params["scenario_id"]], p)
        else:
            X.audit_csv([], p)
        exported[kind] = p
        return {"file_id": kind, "filename": p.name, "download_url": f"/files/{p.name}"}

    c = build_context(rfx=RFX, lines=rfx_line_items(), vendors=VENDORS, questionnaire=QUESTIONNAIRE,
                      answers=QUESTIONNAIRE_ANSWERS, cert_evidence=cert_evidence(), outcomes=outcomes,
                      fx_rates=EXCHANGE_RATES, exporter=exporter)
    c._exported = exported
    return c
