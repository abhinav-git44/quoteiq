# Implementation status

_Last updated 2026-11-06._ This file is deliberately candid about what has and hasn't been executed.

## Build environment caveat
This build was produced in a sandbox **without network access**. pip and npm installs were not possible, and no Anthropic API key was available. As a result:

| Layer | Status |
|---|---|
| Core Python (parsers, grounding, normalization, eligibility, optimiser, analyst tools and loop, RFx co-pilot, exports, document generator) | ✅ **Executed and tested here**: 58 pytest tests pass |
| Claude calls (extraction, certificate reading, analyst, co-pilot) | ⚠️ Request/response handling, schema validation, retry-on-validation-error, tool loop, step limit and error paths are tested with a scripted test client. **No live Claude call has been made.** Run `scripts/run_pipeline.py` + `scripts/eval_extraction.py` first. |
| FastAPI routes, SQLAlchemy models, Alembic migration, services, seed script | ⚠️ Written; `py_compile` and `ruff` (pyflakes rules) are clean; **not executed** (FastAPI, SQLAlchemy and psycopg weren't installable here) |
| Next.js frontend (13 routes) | ⚠️ Written; all 26 TS/TSX files parse cleanly; **`npm install` / `next build` / type-check not run** |
| Playwright e2e (`frontend/e2e/demo.spec.ts`) | ⚠️ Written, not run |

Expect a short fix-up pass on first run of the web stack (typical candidates: a type error, a FastAPI response edge case, a migration detail).

## Implemented
- 5 messy demo documents + 5 certificates, generated deterministically; ground truth for evaluation only
- Parsers with segment-level provenance: XLSX (sheet/row, formula awareness), PDF (page/line/bbox, fine-print marking), DOCX (paragraph/sentence, table rows, footer), image (page detection → perspective warp → lighting normalisation → Tesseract lines with bbox + confidence), EML/TXT (headers, quoted-history marking)
- File validation: extension allow-list, magic bytes, size limit, empty file; safe storage names; sha256; versioning; idempotent jobs
- Claude extraction through a forced tool call with a Pydantic schema, validation-error feedback (3 attempts), vision for photos, an untrusted-content wrapper
- Deterministic grounding: snippet located (exact/fuzzy/other segment), value in source, OCR quality, arithmetic, dimension/ply/BS checks, duplicate matches, flags → heuristic confidence + review queue + exceptions
- Normalization: FX with recorded rate/source/type; UOM (direct, equivalent unit, standard pack, stated pack, derived weight); NOT_COMPARABLE with reasons; NOT_QUOTED; line, order, conditional and early-payment discounts without double counting; tax back-out; freight per load / fixed / per unit / at actuals (assumption); landed cost; full calculation trace
- Questionnaire evaluation with evidence (certificate expiry), PENDING for missing answers, reviewer overrides
- Award: single vendor (with candidate table), lowest-price split (greedy / MILP with K vendors and share cap), **discount-aware pattern search**, balanced (risk-adjusted MILP, 60% cap default); UNALLOCATED lines; risks; assumptions; like-for-like savings vs best single vendor / target / another scenario
- Analyst: 15 validated tools, tool-use loop (10-step cap), history trimming, numeric grounding check surfaced in the UI
- RFx co-pilot with line-count / pricing-basis / questionnaire checks
- Exports: comparison XLSX (with trace comments), exceptions XLSX, award PDF (with approval status), quality PDF, audit CSV
- API: auth (PBKDF2 + HMAC token), dashboard, RFx CRUD/publish/co-pilot, vendors, submissions/upload, document + evidence, extract/retry, comparison, quote detail, exceptions, quality, reviews, questionnaire overrides, analyst chat/history/suggestions, award optimise/list/detail/savings/approve (verification gate), reports, audit log; rate-limit on AI endpoints
- Frontend: login, dashboard, RFx list/detail/co-pilot, vendors, submissions + review queue, extraction review (document + segments + bbox), comparison matrix + quality view + evidence drawer with review actions, analyst chat with tables/charts/tool trace, award scenarios + approval, reports, audit log

## Test results (executed)
```
backend$ pytest -q
58 passed
```
Coverage includes: all parsers on the real demo files; fabricated-price detection; photo handwriting/smudge → review; email "same as last year" → clarification; schema-failure retry; AI-unavailable path; API-error path; vision payload; the spec's ₹500/box vs ₹4,500/100 vs ₹48/pc example; unit/FX/discount/tax/freight rules; **normalized prices from the real documents match ground truth for 133 vendor-line quotes**; eligibility rules; optimiser invariants (no ineligible vendor, no invalid quote, UNALLOCATED, K-vendor and share caps, discount-aware beats naive); analyst loop, tool errors, step limit, numeric grounding; exports open correctly.

## Known limitations
- Trimmed scope (agreed): no settings UI, notifications, or org switcher (the selector is display-only).
- Scanned PDFs (no text layer) are rejected with a clear message rather than OCR'd; `.xls` must be re-saved as `.xlsx`.
- The weight model is approximate (ignores flute take-up); it is always disclosed and flagged for review.
- Freight per load is allocated by value across *all* the vendor's quoted lines, not re-estimated per scenario.
- Confidence weights are hand-set heuristics, not calibrated.
- Background jobs use an in-process thread pool (fine for a demo; use a queue in production).
- The default model id (`claude-sonnet-5-5`) is configuration; set `ANTHROPIC_MODEL` if your account uses another.

## Remaining work (first run)
1. `pip install -r backend/requirements.txt`, `alembic upgrade head`, `seed_demo.py --extract`, then fix anything the first real run surfaces.
2. `scripts/eval_extraction.py`: record the real accuracy and silent-error numbers in the decision note.
3. `npm install && npm run typecheck && npm run build`, then fix type errors.
4. Run the Playwright spec; record the analyst walkthrough.
