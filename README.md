# QuoteIQ — from vendor quotations to confident procurement decisions

Aerchain PM take-home ("Kill the Quote Spreadsheet"). A buyer drafts an RFx with an AI co-pilot. Vendors reply in five messy formats (an off-template Excel, a PDF with a footnote discount, a Word letter, an angled phone photo, a USD per-kg email). QuoteIQ extracts and verifies every value, normalizes everything to one basis, and lets the buyer interrogate the result in plain language, all the way to a defensible, human-approved award.

**All data is synthetic.** Read first: [`docs/PRODUCT_DECISIONS.md`](docs/PRODUCT_DECISIONS.md) (one-page note) · [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)

## Features
- **RFx co-pilot**: conversational drafting into a validated schema (line-count and pricing-basis checks); editable; save as draft or publish (email stubbed).
- **Document intelligence**: XLSX, PDF, DOCX, JPG/PNG (perspective correction + OCR + vision), EML/TXT. Every value carries a cited source segment and is re-verified deterministically; confidence comes from those checks.
- **Normalization**: INR/USD/EUR/GBP with disclosed rates; per piece, per 100/1000, stated packs, per kg (via a disclosed box-weight model); discounts with conditions; tax back-out; freight allocation (per load, per unit, at actuals); `NOT_QUOTED` is never zero.
- **Quality**: a 10-question questionnaire with deterministic rules. ISO evidence is read from the attached certificate (an expired certificate means FAIL). Blank mandatory answers stay PENDING.
- **Comparison**: a 30×5 matrix (TanStack Table): sticky columns, base/landed and as-quoted/normalized toggles, filters, and an evidence drawer with the calculation trace, checks and source highlight.
- **AI analyst**: a Claude tool-use loop over 15 restricted tools. It returns tables, charts and exports; every number is checked against tool output.
- **Award**: single vendor, lowest-price split (with a discount-aware pattern search), and balanced (MILP with a concentration cap). Savings are like-for-like. Approval is blocked while awarded values are unverified.
- **Exports and audit**: comparison XLSX, exceptions XLSX, award PDF, quality PDF, audit CSV. An append-only audit log.

## Prerequisites
Python 3.12+, Node 20+, PostgreSQL 15+ (or Docker), Tesseract OCR (`apt install tesseract-ocr` / `brew install tesseract`), an **Anthropic API key**.

## Quick start (Docker)
```bash
cp .env.example .env            # set ANTHROPIC_API_KEY
docker compose up -d --build
docker compose exec api python /app/scripts/seed_demo.py --extract
open http://localhost:3000      # buyer@kaveri.example / quoteiq-demo
```

## Local development
```bash
cp .env.example .env && export $(grep -v '^#' .env | xargs)
docker compose up -d db                         # or use your own Postgres; set DATABASE_URL

cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
cd .. && python scripts/seed_demo.py --extract  # registers the 5 quotes + 5 certificates, runs REAL extraction
cd backend && uvicorn app.main:app --reload --port 8000

cd ../frontend && npm install && npm run dev    # http://localhost:3000
```
**Demo credentials:** `buyer@kaveri.example` / `quoteiq-demo` (buyer) · `vp@kaveri.example` / `quoteiq-demo` (approver).

Re-seed from scratch: `python scripts/seed_demo.py --reset --extract` (this drops all tables).

## Without the web stack
```bash
export ANTHROPIC_API_KEY=...
python scripts/run_pipeline.py                                   # real extraction of all 5 quotes + certificates
python scripts/eval_extraction.py                                # accuracy vs ground truth, incl. SILENT errors
python scripts/run_pipeline.py --skip-extract --ask "What if we split it, cheapest per line, only among vendors who cleared quality?"
```

## Demo data
`python scripts/generate_documents.py` regenerates `demo_data/` deterministically. That covers 30 corrugated lines (₹2.9 cr at base prices) and 5 vendors with planted edge cases (see `demo_data/ground_truth.json`, which only the eval script and tests read; the app never does).

| Vendor | Format | Planted edges |
|---|---|---|
| PackPro | XLSX, own template | own item codes, re-ordered rows, per-100 pricing, discount column, BS-20 spec deviation |
| EcoCarton | 2-page PDF | 27/30 lines, **4% discount in page-2 fine print, conditional on all quoted items**, freight per truck |
| Prime | DOCX letter | commercials in paragraphs, per-bundle and per-box (unstated pack) pricing, cash discount, volume-conditional price; **ISO certificate expired** |
| Shree | angled phone photo | perspective, uneven light, **handwritten correction**, **coffee smudge on a price**, 28/30, per-piece transport |
| GlobalPack | email, USD | **per-kg prices**, category pricing, "rest same as last year", freight at actuals, quoted history |

## Configuration (`.env`)
`ANTHROPIC_MODEL` (any current Claude model with vision and tool use) · `CONFIDENCE_HIGH` / `CONFIDENCE_REVIEW_BELOW` · `FREIGHT_AT_ACTUALS_ASSUMED_PCT` · `APPLY_EARLY_PAYMENT_DISCOUNTS` · `DERIVED_WEIGHT_REQUIRES_REVIEW` · `COMPARE_EX_TAX` · `MAX_UPLOAD_SIZE_MB` · `JWT_SECRET`. Without `ANTHROPIC_API_KEY` the app runs, but extraction ends as `AI_UNAVAILABLE` (parsed text is visible, nothing is invented), and the co-pilot and analyst return 503.

## Tests
```bash
cd backend && pytest -q          # core: parsers, grounding, extraction retry paths, normalization, eligibility, optimiser, analyst loop, exports
cd frontend && npx playwright test   # against a running, seeded stack
```

## Deployment
`docker-compose.yml` builds the `api` (FastAPI + Tesseract) and `web` (Next.js standalone) images with Postgres. For production: set `JWT_SECRET`, put storage on S3-compatible object storage (`services/common.store_file` is the single seam), run the extraction worker as a separate process, and restrict CORS.
