# Decisions

*Each entry is **Problem → Evidence → Decision → Result**. Evidence comes from real testing in [feedback-notes.md](feedback-notes.md) or from the design constraints in [problem-statement.md](problem-statement.md). This is the record of *why* the product is the way it is.*

Legend for Evidence source: `[design]` = decided up front from the problem; `[R1]` = Round 1 testing (2026-10-12).

---

## D1 — The AI is never trusted blindly `[design]`

- **Problem:** A vision model can be *confidently wrong* about a receipt (amount, date, VAT). Trusting it silently would corrupt the ledger.
- **Evidence:** Receipts are financial records; a single wrong number breaks reconciliation and the month-end.
- **Decision:** The model only *reads*. A **confidence gate** plus **deterministic guardrails** (`backend/app/services/validation.py`) decide posting. All VAT/reconciliation/close math is computed in code. Uncertain reads go to a human review queue.
- **Result:** Bad reads are caught, not posted. See D7/D8 for real catches.

## D2 — Bank data via CSV import, not open-banking `[design]`

- **Problem:** How to get bank transactions for reconciliation.
- **Evidence:** Open-banking APIs mean OAuth, per-bank integrations, approval, and credential risk — heavy for a single-user portfolio tool.
- **Decision:** Import a bank-statement **CSV** (configurable column mapping).
- **Result:** Works with any bank, no secrets, demoable in minutes. Reconciliation logic is identical regardless of source.

## D3 — Cash is counted but excluded from reconciliation `[design]`

- **Problem:** Cash spend has nothing in the bank to match against.
- **Evidence:** If cash were reconciled, every cash expense would show as a false "unmatched" exception.
- **Decision:** Cash counts in totals/categories but is skipped by the reconciliation engine and never flagged as an exception.
- **Result:** The exceptions list stays trustworthy — it only shows real problems.

## D4 — Cancel/refund emails are draft-only `[design]`

- **Problem:** Automating subscription cancellations risks sending something the user didn't intend.
- **Evidence:** Nothing financial should ever auto-send (a core hard rule).
- **Decision:** The hybrid n8n flow creates a **Gmail draft** only; the user reviews and sends it themselves.
- **Result:** Full automation of the tedious part (writing the email) with a human gate on the irreversible part.

## D5 — Hybrid architecture: logic in FastAPI, n8n only for delivery `[design]`

- **Problem:** Where should subscription detection, draft writing, and email delivery live?
- **Evidence:** Logic in n8n isn't unit-testable; logic in code is.
- **Decision:** All logic (detection, savings, draft text) in FastAPI with tests; n8n used *only* as the Gmail-draft delivery + cron re-detect layer.
- **Result:** The accounting-critical paths are covered by pytest; n8n stays a thin, swappable integration.

## D6 — Deterministic extraction guardrails, independent of model confidence `[design]` + `[R1]`

- **Problem:** The model's self-reported confidence can be high even when it's wrong.
- **Evidence (R1):** gpt-4o read a 2026 receipt's date as 2023 at 0.9 confidence.
- **Decision:** `validation.py` runs checks in code regardless of confidence — no total → reject; future/old date, low confidence, or line-items≠total → route to review with human-readable reasons.
- **Result:** The 2023 misread was caught and routed to review instead of auto-posting.

## D7 — Portuguese (European) day-first date interpretation `[R1]`

- **Problem:** Dates on Portuguese receipts are day-first (`DD/MM/YYYY`), but the model defaulted to misreading them (incl. a "receipt from the future" false flag).
- **Evidence (R1):** `1000017784.jpg` (real date 2026-10-06) was read as a future date; another receipt read 2026-10-03 as 2023-10-26.
- **Decision:** Added explicit date rules to the extraction prompt (day-first; `YY-MM-DD` short dates; prefer the terminal/transaction date; output ISO) and enabled `detail:"high"` vision.
- **Result:** `1000017784.jpg` now reads **2026-10-06**, €4.14, both line items → auto-posts clean. (Badly-shot/rotated photos still route to review — see D9.)

## D8 — Only confirmed expenses hit the ledger `[R1]`

- **Problem:** Posting a reviewed receipt didn't change Total spent / VAT / exceptions — contradicting the UI's "nothing posts until you confirm."
- **Evidence (R1):** `close`, `exceptions`, and `reconcile` all counted `pending_review` rows already, so approving one only flipped its status.
- **Decision:** Aggregations and reconciliation now count **confirmed** rows only; the dashboard drill-downs match.
- **Result:** Verified — a review item stays out of the totals; pressing Post moves Total spent €63.62→€111.86 and the exception count 3→4.

## D9 — Photo quality drives extraction; guardrails + guidance, not false precision `[R1]`

- **Problem:** A sideways, crumpled, dark-background receipt (`1000017785.jpg`) made gpt-4o hallucinate date/total/items even at high detail.
- **Evidence (R1):** No prompt change reliably fixed it; the same store shot flat/upright read perfectly.
- **Decision:** Keep the prompt/detail improvements, add an in-app **capture hint** (shoot flat, upright, good light), and rely on guardrails to route bad reads to review. Measure accuracy on normal-quality photos.
- **Result:** Honest failure mode — the system flags what it can't read instead of guessing. (Strong "AI knows when it's unsure" story.)

## D10 — Every dashboard number traces back to its expenses `[R1]`

- **Problem:** Dashboard figures (total spent, VAT, card/cash, reconciled, by-category) were read-only dead-ends.
- **Evidence (R1):** User couldn't see what made up a number or open the underlying receipts.
- **Decision:** Every stat card and category row is a **drill-down** to the source expenses (with receipt view + delete); lists are month-scoped so they sum back to the card. "Spending by category" also opens *all* month expenses newest-first.
- **Result:** The "one ledger, every number traces back" principle is now reachable in the UI.

## D11 — Surface possible duplicates where the user acts on them `[R1]`

- **Problem:** Duplicates flagged in reconciliation were hard to find/compare once in the Ledger.
- **Evidence (R1):** User uploaded a duplicate, hit Resolve, then struggled to locate the two rows.
- **Decision:** The duplicate exception deep-links to `Ledger?view=duplicates` (auto-filtered); duplicate rows show a "Possible duplicate" badge + highlight + delete.
- **Result:** The pair sits side by side, impossible to miss, one click to remove the extra.

## D12 — Per-line VAT: a receipt can hold multiple rates `[design]` + `[R2]`

- **Problem:** Each expense stored a single VAT rate, so a mixed-rate receipt (e.g. 6% + 13% + 23% on one Continente ticket) was flattened to its dominant rate. The "VAT by rate" view then put the whole receipt's VAT in one bucket — subtly wrong, and it understated the accounting rigor the project is meant to prove.
- **Evidence:** Round 1 logged this as a known simplification; **Round 2** confirmed it on a real 3-rate Continente receipt (`1000017708.jpg`) where the review Edit form only let the user enter one rate (see [feedback-notes.md](feedback-notes.md) R2). Portuguese receipts tag each line with a VAT code and print a summary table mapping codes to rates — the information to do this correctly is on the receipt.
- **Decision:** Add an `expense_line_items` table; each line carries its own `vat_rate`. VAT is **summed per rate in code** (`vat.vat_breakdown`, Decimal). It's computed **bucket-first** — VAT is split once on each rate's *gross total*, not summed per line — so it reconciles to the printed Portuguese IVA summary to the cent. The expense's stored `vat_amount` becomes the per-rate sum; the dominant rate is kept for the single-rate display. The breakdown is produced by extraction **and** by a **multi-rate editor in the review queue** (add one line per rate), so a mis-read or manually-entered receipt can be corrected by hand. Dashboard/Ledger VAT-by-rate views split a mixed receipt across rates, falling back to the single stored rate for expenses with no line items.
- **Result:** Verified end-to-end against live Supabase. The real 3-rate Continente receipt reconciles to **6% €0.32 · 13% €0.66 · 23% €0.02 = €1.00**, gross €11.58 — matching the printed IVA summary exactly (bucket rounding fixed a per-line €0.01 drift). Line items cascade-delete with the expense. *(Remaining real-test step: re-upload the receipt through gpt-4o with the fixed date prompt and confirm it auto-reads the 3 rates vs. entering them in review.)*

## D13 — Flag duplicates at upload, before they post `[R2]`

- **Problem:** Duplicate detection only ran during reconciliation, so a re-uploaded receipt could auto-post to the ledger and only surface as a duplicate later.
- **Evidence (R2):** With a clean ledger, re-snapping the same receipt would silently create a second identical row.
- **Decision:** `/extract` now checks the ledger at upload time for an existing row with the **same vendor + amount + date** (`repo.find_duplicates`). A match **forces the receipt into the review queue** (never auto-posts) with a clear reason, and the response carries `duplicate_of`. The snap screen shows an in-modal warning naming the existing expense so the user can compare and discard whichever is the duplicate. Consistent with the human-confirm-gate rule (D1) and the duplicate-surfacing work (D11).
- **Result:** Verified end-to-end — a second identical upload returns `duplicate_of` and routes to review with "Possible duplicate — … already in your ledger. Check before posting." Nothing posts automatically.

---

## Planned (decided, not yet built)

- **LLM-assisted categorization** — for vendors the rules miss (e.g. Continente → Groceries).
