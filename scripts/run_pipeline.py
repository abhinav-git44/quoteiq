"""Run the REAL AI pipeline on the demo documents without the web app.

  export GEMINI_API_KEY=...   # free (or ANTHROPIC_API_KEY)
  python scripts/run_pipeline.py                      # extract all 5 quotes + 5 certificates
  python scripts/run_pipeline.py --ask "What if we split it, cheapest per line, only among vendors who cleared quality?"

Outputs: storage/pipeline/<vendor>.outcome.json, certificates.json. Then run
  python scripts/eval_extraction.py   to score extraction against ground truth.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai.llm import get_llm  # noqa: E402
from app.analyst.agent import run_analyst  # noqa: E402
from app.analyst.builder import build_context  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.demo.catalog import EXCHANGE_RATES, QUESTIONNAIRE, QUESTIONNAIRE_ANSWERS, RFX, VENDORS, rfx_line_items  # noqa: E402
from app.domain.extraction import ExtractionOutcome  # noqa: E402
from app.extraction.pipeline import extract_certificate, extract_quotation  # noqa: E402

FILES = {"V-A": "vendor_a_packpro_quotation.xlsx", "V-B": "vendor_b_ecocarton_quotation.pdf",
         "V-C": "vendor_c_prime_quotation.docx", "V-D": "vendor_d_shree_quotation_photo.jpg",
         "V-E": "vendor_e_globalpack_email.eml"}
OUT = ROOT / "storage" / "pipeline"


def extract_all(llm):
    OUT.mkdir(parents=True, exist_ok=True)
    names = {v["vendor_id"]: v["name"] for v in VENDORS}
    for vid, fn in FILES.items():
        t = time.time()
        oc = extract_quotation(ROOT / "demo_data" / fn, rfx_line_items(), llm, derived_dir=OUT / "derived", vendor_hint=names[vid])
        (OUT / f"{vid}.outcome.json").write_text(oc.model_dump_json(indent=1))
        review = sum(1 for l in oc.lines if l.review_required)
        cov = {}
        for v in oc.coverage.values():
            cov[v] = cov.get(v, 0) + 1
        print(f"{vid} {fn:40s} {oc.status:13s} {time.time() - t:5.1f}s  lines={len(oc.lines)} review={review} coverage={cov}"
              + (f"  ERROR: {oc.error}" if oc.error else ""))
    certs = {}
    for vid in FILES:
        r = extract_certificate(ROOT / "demo_data" / "certificates" / f"{vid.lower()}_iso9001_certificate.pdf", llm)
        c = r.get("certificate")
        certs[vid] = {"status": r["status"], "valid_until": c.valid_until.value if c else None,
                      "number": c.certificate_number.value if c else None, "confidence": r.get("valid_until_confidence"),
                      "segment_id": c.valid_until.segment_id if c else None, "snippet": c.valid_until.snippet if c else None}
        print(f"{vid} certificate valid_until={certs[vid]['valid_until']} conf={certs[vid]['confidence']}")
    (OUT / "certificates.json").write_text(json.dumps(certs, indent=1))


def load_context():
    outcomes = {vid: ExtractionOutcome.model_validate_json((OUT / f"{vid}.outcome.json").read_text())
                for vid in FILES if (OUT / f"{vid}.outcome.json").exists()}
    certs = json.loads((OUT / "certificates.json").read_text()) if (OUT / "certificates.json").exists() else {}
    return build_context(rfx=RFX, lines=rfx_line_items(), vendors=VENDORS, questionnaire=QUESTIONNAIRE,
                         answers=QUESTIONNAIRE_ANSWERS, cert_evidence=certs, outcomes=outcomes, fx_rates=EXCHANGE_RATES)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", action="append", help="Analyst question (repeatable)")
    ap.add_argument("--skip-extract", action="store_true")
    a = ap.parse_args()
    llm = get_llm()
    if llm is None:
        sys.exit("No AI key set (GEMINI_API_KEY or ANTHROPIC_API_KEY). Nothing will be fabricated; set a key and re-run.")
    print(f"Provider: {get_settings().provider}  model: {get_settings().active_model}")
    if not a.skip_extract:
        extract_all(llm)
    if a.ask:
        ctx = load_context()
        history = []
        for q in a.ask:
            turn = run_analyst(ctx, llm, q, history)
            history = turn.messages
            print(f"\nQ: {q}\n" + "-" * 80)
            print("Tools:", ", ".join(f"{c.name}{'' if c.ok else ' (error)'}" for c in turn.tool_calls))
            print(turn.answer)
            if turn.ungrounded_numbers:
                print("⚠ Numbers not traced to a tool result:", turn.ungrounded_numbers)


if __name__ == "__main__":
    main()
