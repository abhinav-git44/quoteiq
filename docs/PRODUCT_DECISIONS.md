# QuoteIQ — what I decided, and what I left out

*One-page note for the Aerchain take-home. Appendices below the line are reference.*

**The bet.** Reading a messy quote is now a commodity: a multimodal model can read an angled photo or a footnote. The product problem is **comparability and trust**. Can five answers in five shapes be put on one basis, and can a buyer see exactly why each number is on the screen? So I put most of the effort into normalization, provenance and refusal to guess, and kept RFx drafting, email and the vendor portal thin.

**Decisions that shape everything**

1. **Model reads, code calculates.** Claude extracts values *as written* (price, unit, currency, conditions), each with a cited segment id and a verbatim snippet. All conversion, FX, discount, freight and award maths is deterministic Python with a step-by-step trace. The analyst can only call 15 restricted tools; there's no SQL and no free arithmetic.
2. **Confidence comes from checks, not from the model's opinion.** Every value is re-verified against the document: is the snippet really there, is the number really in it, does qty × rate reconcile, do the dimensions and ply match the RFx line, what did OCR think of that row. The score is labelled a *heuristic*, not a probability. Below 70 the value goes to a review queue.
3. **Never guess; say why.** Missing quotes are `NOT_QUOTED`, never ₹0. "Per box" without a pack size is `NOT_COMPARABLE`, with the reason shown. "Rest same as last year" is `NEEDS_CLARIFICATION`, and the system drafts the vendor email. A smudged price is `UNREADABLE`. A per-kg price *is* converted, using a disclosed box-weight model (blank area × board GSM), but it is flagged as an assumption until the buyer accepts it.
4. **A trust gate at the money moment.** You can explore scenarios on unverified data, but **an award can't be approved while any awarded value is unverified**, or with unallocated lines unless you acknowledge them. Approval recomputes from current data and is audit-logged.
5. **Evidence is checked, not claimed.** Prime Packaging answered "yes, ISO 9001". The attached certificate expired on 31 Mar 2026, so the vendor is INELIGIBLE, with the reason shown. A blank mandatory answer stays PENDING; it never auto-passes.
6. **No misleading totals.** When coverage differs, no grand total is shown. Savings are computed like-for-like, only on lines both scenarios allocate.

**The better problem I found.** The VP's "cheapest per line among qualified vendors" is the *wrong optimisation*. EcoCarton's 4% discount sits in page-2 fine print and applies only if it wins *every* line it quoted. Cheapest-per-line forfeits it. On the demo data:

| Scenario (eligible vendors only, base price ex-GST) | Net |
|---|---|
| Best single vendor (PackPro, 30/30 lines) | ₹2.93 cr |
| VP's split: cheapest per line | ₹2.81 cr |
| **Discount-aware split: EcoCarton all 27 quoted lines + PackPro 3** | **₹2.73 cr (−₹19.6 L, 6.7% vs single vendor)** |
| For reference: the same split allowing ineligible Prime | ₹2.69 cr (the quality rule costs ₹4.5 L) |

The optimiser therefore searches award *patterns* that earn conditional discounts and shows the plain alternative next to it. It also reports the trade-off this creates: 85% concentration on one vendor, which the Balanced strategy caps at 60%. *(The figures assume the extraction matches ground truth. `scripts/eval_extraction.py` measures how close a real run gets.)*

A broader version of the same point: **comparability is designed in the RFx, not repaired afterwards.** The co-pilot insists on one pricing basis per line (unit, currency, ex-GST, delivered), and the most valuable AI loop isn't parsing. It's the clarification email that closes the gaps, because that, not reading, is where the nine days go.

**Deliberately left out:** a real email channel and vendor portal (stubbed; uploads stand in), multi-round negotiation and e-auctions, ERP/PO integration, live FX feeds (rates are marked *assumed demo*), payment-term NPV (shown but not priced in), scanned-PDF OCR, .xls without re-saving, multi-tenant permissions beyond org scoping, settings UI, and calibrated confidence (that needs real labelled history).

**What I'd measure next:** silent-error rate (wrong values that were *not* flagged; the only error that costs money), the review rate per format, and time from last quote to approved award.

---

## Appendix A — Problem, users, assumptions
- **Users:** a category buyer (owns the RFx, resolves review items) and a VP or approver (asks "what if", approves). Both are numerate and sceptical, and both have ₹ crore at stake.
- **Category:** corrugated packaging. It's the brief's example, and it has natural unit trouble (per piece, per 100, per bundle, per kg) that exercises normalization. INR base currency, with GST excluded from comparisons because it's input-creditable.
- **Assumptions:** vendors answer the questionnaire through a structured portal form (stubbed). Quotes arrive as files. One quotation document per vendor is current; re-uploads are versioned.

## Appendix B — Architecture decisions
- Next.js + FastAPI + PostgreSQL, as specified. The **core is framework-free Python** (extraction, grounding, normalization, eligibility, optimiser, analyst tools, exports). It is fully unit-tested and reused by the API, the scripts and the tests.
- Claude via the Messages API over HTTP (no SDK dependency). Structured output comes from **forced tool calls** with Pydantic-generated JSON Schemas, and validation errors are fed back for up to 3 attempts. Vision is used for photos, alongside OCR text, so both views are cross-checked.
- Optimiser: greedy when unconstrained, MILP (SciPy/HiGHS) when there are vendor-count or share caps, plus an outer search over conditional-discount patterns.
- Background extraction runs on a thread pool with idempotency keys (document hash + model + prompt version).

## Appendix C — AI design
- **Extraction prompt rules:** record what is written; cite segment + verbatim snippet; never convert; flag handwriting, illegibility, category prices and spec deviations; route vague references to `unresolved_references`.
- **Grounding penalties** (see `extraction/grounding.py`): snippet not found −45, value not in source −35, OCR < 60 −30, spec conflict −35, handwritten −22, illegible −60, and so on. These are transparent constants, shown per value in the UI.
- **Analyst:** a system prompt forbids un-tooled numbers. After the answer, a numeric grounding check matches every figure against tool outputs (allowing lakh/crore and % formats), and anything untraced is shown to the user in amber.

## Appendix D — Trust and safety
- Vendor documents are wrapped as untrusted data, and the prompts instruct the model to ignore and report embedded instructions.
- Uploads are checked by extension and magic bytes, size-limited, renamed safely and stored outside the web root.
- Human corrections are layered on top of extraction (`field_reviews`) and never overwrite it.
- Approved scenarios are immutable.
- The audit log covers RFx, uploads, extraction, corrections, normalization, questionnaire overrides, analyst questions, scenarios, approvals and exports.

## Appendix E — Known limitations and roadmap
- Confidence weights are hand-set. Next step: calibrate them against reviewed outcomes.
- The weight model ignores flute take-up and trim. Next step: learn a per-vendor kg→piece factor from confirmed quotes.
- Freight allocation is by value. Next step: allocate by load or volume using pallet patterns.
- The analyst keeps the last 6 turns. Next step: summarise long sessions.
- Roadmap: a vendor-facing clarification portal, re-quote rounds with deltas, payment-term NPV, live FX with locked rates, and prior-contract memory so that "same as last year" can actually be resolved.
