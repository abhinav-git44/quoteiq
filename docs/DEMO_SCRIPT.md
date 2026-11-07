# Demo script (10 minutes)

**Setup before the call:** run `python scripts/seed_demo.py --extract` with `ANTHROPIC_API_KEY` set, then `python scripts/eval_extraction.py` so you know the real accuracy numbers. Log in as `buyer@kaveri.example`.

| Time | Screen | What to show | Line to say |
|---|---|---|---|
| 0:00 | Dashboard | 5 quotes received; values to verify; extraction success rate | "Nine days of quotes, in five shapes, landed in one place." |
| 0:45 | RFx → co-pilot | Paste the example prompt; the draft fills; issues banner if ≠ 30 lines; pricing basis | "Comparability starts here: one unit, ex-GST, delivered, for every line." |
| 2:00 | Submissions | Five formats, extraction statuses, review queue on the right | "Every file goes through the same pipeline. Nothing is pre-loaded." |
| 2:45 | Extraction review: the **photo** | Toggle original/corrected; click L06 → handwritten 74.28 over struck 78.28; L19 → OCR "8:39", confidence 0 | "When it isn't sure, it says so, and shows you where to look." |
| 3:45 | Extraction review: the **PDF** | Footnote on page 2 marked *fine print*, captured as a conditional 4% discount | "The discount nobody reads." |
| 4:15 | Extraction review: the **email** | "Rest same as last year" → 11 lines NEEDS CLARIFICATION; per-kg prices | "It refuses to invent last year's prices." |
| 4:45 | Comparison | 30×5 matrix, coverage warning, no grand total; toggle *As quoted* vs *Normalized*; open a GlobalPack cell → kg→piece trace with weight model + FX (assumed demo rate) | "Same lines, same units, same currency, and every number has a receipt." |
| 5:45 | Comparison → Quality view | Prime: yes to ISO, but the certificate expired 31 Mar 2026 → INELIGIBLE; Shree: blank traceability answer → PENDING | "A 'yes' isn't evidence." |
| 6:15 | Analyst | Ask the VP question (below). Show the tool trace and the grounded-numbers badge | |
| 8:00 | Award | Run *Lowest per line (plain)* then *discount-aware*; compare cards; risks (85% concentration); try **Approve**, which is blocked by unverified values | "It's allowed to explore on unverified data, but not to sign." |
| 9:15 | Award → PDF, Reports, Audit log | Download the award PDF; open the audit log entry | "Defensible means reproducible." |

## Analyst questions (in order)
1. *Who is the cheapest vendor overall?* It should refuse the naive answer: coverage differs, Prime is ineligible. It should use `compare_vendor_costs` on common lines.
2. *What if we split it, cheapest per line, but only among vendors who cleared the quality questionnaire?* `optimize_split_award`. Expect the discount-aware pattern and a mention of the plain alternative.
3. *How much does that save versus giving it all to one vendor?* `calculate_savings`, like-for-like.
4. *Which numbers are you not sure about, and do any of them change the award?* `get_extraction_exceptions` + allocations.
5. *What is excluding Prime costing us?* Scenario with `eligible_only=false` vs the default.
6. *What happens if freight is included?* `cost_basis=landed`; GlobalPack's freight-at-actuals assumption is disclosed.
7. *Cap any vendor at 60% — what does that cost?* Balanced or `max_share_pct`.
8. *Draft a clarification email to GlobalPack.* `draft_vendor_clarification`.
9. *Export the award recommendation.* `create_export_report`.

## If they drive
- **Uploading their own file**: any xlsx, pdf, docx, jpg, png, txt or eml goes through the same path. Expect review flags rather than silent values.
- **"Change the FX rate to 90"**: `calculate_normalized_cost` with `fx_rate_override` (what-if, not persisted).
- **Correct a value**: in the drawer, choose **Correct…**, enter the value and a comment, and save. The comparison, scenarios and audit log update.
