# Decisions

*Each entry is **Problem → Evidence → Decision → Result**. Evidence comes from real testing in [feedback-notes.md](feedback-notes.md) or from the design constraints in [problem-statement.md](problem-statement.md). This is the record of *why* the product is the way it is.*

Legend for Evidence source: `[design]` = decided up front from the problem; `[R1]` = Round 1 testing (2026-10-12); `[R2]` = Round 2 (2026-10-13); `[R3]` = Round 3 (2026-10-15).

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

## D14 — The receipt's printed VAT summary table is the VAT source of truth `[R3]`

- **Problem:** Computing VAT from the model's reading of per-item amounts failed on crumpled receipts — it misread/fabricated line amounts and produced wrong VAT (e.g. 6% €0.09 vs the printed €0.15).
- **Evidence (R3):** Portuguese receipts print an exact "IVA / RESUMO DO IVA" summary (per rate: net, VAT, gross). It's the legal figure and a compact, structured block — more reliable than re-deriving from item lines.
- **Decision:** Extraction **transcribes** that table into `tax_lines` (copy printed numbers, never compute). When its gross-per-rate ties to the total, it becomes the authoritative VAT breakdown (one gross bucket per rate, which also seeds the review editor). The prompt forbids inventing/adjusting any figure to force a total.
- **Result:** Reproduces printed figures to the cent (Continente `1000017808.jpg`: 6% €0.15 · 23% €0.30 · total VAT €0.45, gross €4.17). When the table can't be read it falls back to per-line VAT and the guardrails take over (see D21).

## D15 — LLM-suggested categorization: rules first, model fills the gaps `[R3]`

- **Problem:** The keyword categorizer returned "Uncategorized" for vendors it didn't know (Continente, PD OLAIAS, Pingo Doce).
- **Evidence (R3):** Those are grocery stores the rules simply didn't list; the model is already reading the receipt.
- **Decision:** gpt-4o suggests a `category` during extraction. **Deterministic keyword rules run first** (fast, free, auditable); an unknown vendor falls back to the model's suggestion, accepted only if it matches a real category (else "Uncategorized"). Added a **Tobacco** category.
- **Result:** The three gap vendors now resolve to Groceries; rules still win for known vendors; a bad guess degrades safely. (Closes the last "Planned" item.)

## D16 — Deterministic date year-repair + focused re-read `[R3]`

- **Problem:** The #1 extraction error on crumpled receipts is a misread **year** (day/month fine): 2026 read as 2021/2023. A prompt alone didn't fix it.
- **Evidence (R3):** gpt-4o read a 2026-10-14 receipt as 2021-10-14 **twice**, confidently; Auchan's `Data Emissão: 2026-10-13` read as 2021-10-14.
- **Decision:** When a date looks implausible, (1) a **focused second pass re-reads only the date**, accepted only if plausible; then (2) a **code-level year-repair** snaps the year to the most recent plausible one (never a future date, only when month/day land in the recent window) and **forces review** with a "year looked misread — corrected X→Y, confirm" note. Prompt also learns the `Data Emissão` ISO date and the `YY-MM-DD` terminal format.
- **Result:** A misread year is corrected and surfaced for one-click confirmation instead of silently posting a wrong date; the day stays editable in review.

## D17 — Discounts are modelled, never counted as products `[R3]`

- **Problem:** Loyalty discounts (POUPANÇA) and promotions (Uber Eats "Special Offer") were read as products or inflated the amount.
- **Evidence (R3):** Uber Eats `1000017810.jpg`: Subtotal €32.38 − Special Offer €13.99 = **€18.39 paid**; items at full price sum above the paid amount.
- **Decision:** Discount lines (POUPANÇA / DESCONTO / Special Offer / Promoção / parenthesised negatives) are **never** line items; `total` is always the amount **paid after** discounts; `discount_total` is captured. The line-item reconciliation check is skipped when a discount is present, and a discounted receipt's lines are **scaled proportionally to the amount paid** so VAT is computed on what was paid.
- **Result:** The amount stored is what you paid (€18.39), and the VAT estimate reconciles to it; discounted receipts no longer false-flag.

## D18 — Estimated VAT from product type when the receipt prints none `[R3]`

- **Problem:** Delivery/simple-till receipts (Uber Eats) list products but print no VAT; a normal user can't know a pizza is 13% and a drink 23%.
- **Evidence (R3):** The user asked for a suggestion from general tax knowledge rather than leaving VAT blank.
- **Decision:** When no VAT is printed, gpt-4o **estimates** the standard mainland-Portugal rate per product (prepared food/pizza 13%, drinks/alcohol/snacks 23%, basic groceries 6%); VAT is **computed in code**, the receipt is routed to **review marked "suggested"** (amber VAT fields + hover tooltip, cleared once the user edits a rate), and it only estimates when nothing is printed (printed VAT is never overridden). A real **0%** (tobacco) is a captured answer — not "missing VAT."
- **Result:** VAT-less receipts get a sensible, clearly-labelled estimate the user confirms — honest, not blind (consistent with D1).

## D19 — Amount paid = net + VAT (net-vs-gross correction) `[R3]`

- **Problem:** Some receipts print a prominent **net/BASE** line; the model read *that* as the total, understating the amount paid.
- **Evidence (R3):** Auchan `1000017811.jpg` stored €3.77 (printed BASE) instead of the €4.18 actually paid; the line items correctly summed to €4.18.
- **Decision:** When the itemized/printed breakdown gives a coherent gross and the model's "total" matches its **net** rather than its **gross**, store the **gross (net + VAT)** as the amount paid. The expense-detail view derives its grand total from the line items so it always reconciles.
- **Result:** Auchan now stores €4.18 (net €3.77 + VAT €0.41); discounted receipts (already scaled to the paid amount) are unaffected.

## D20 — Server-side receipt auto-rotation `[R3]`

- **Problem:** A sideways/upside-down photo is the single biggest cause of misread dates and VAT, and the model can only *mentally* re-orient.
- **Evidence (R3):** A sideways Auchan receipt misread its date and VAT; once straightened it read correctly.
- **Decision:** Before the model reads it, the backend (Pillow, optional dep) applies the photo's **EXIF orientation**, detects **landscape** (a likely sideways receipt), and re-reads at **90°/270°/0°** (180° fallback for weak portrait reads), keeping the orientation whose read looks most upright/reconciling (a reconciliation-aware **read score**). The **straightened image is stored**, so saved receipts display upright. Cost-aware: a good upright photo costs one read.
- **Result:** Sideways receipts are straightened deterministically; the earlier prompt-only "mentally rotate" guidance is now backed by real pixel rotation.

## D21 — Self-consistency guardrail + retake, for reads that look fine but aren't `[R3]`

- **Problem:** On a badly crumpled receipt the model can produce a **confident, internally-reconciling, but wrong** read (even inventing items) that every total-based check passes — so it auto-posts.
- **Evidence (R3):** A crumpled Continente auto-posted with a hallucinated breakdown whose fake numbers summed to the €10.89 total; its printed VAT table and its item lines disagreed per-rate by €1.69.
- **Decision:** When the model returns **both** a printed VAT table **and** item lines, their per-rate gross must agree (shown item prices are already net of loyalty discounts on these chains); a large mismatch means an **unreliable read** → **don't auto-post**, route to review. Plus a **retake prompt** at upload and a **Retake** button in the review queue when a read looks low-quality (reconcile mismatch, misread/repaired date, low confidence, or this inconsistency). A **read-twice-and-compare** consensus mode is deferred as a future option.
- **Result:** The hallucinated Continente now routes to review instead of auto-posting; the user retakes (flatter) or edits. Honest limit (extends D9): the system reliably *catches and hands off* bad reads — it can't invent correct digits off creased paper.

---

## Planned (decided, not yet built)

- **Extraction-accuracy eval harness** — a labelled receipt set + `backend/scripts/eval_extraction.py` to produce a real field-level accuracy number for the README "Results".
- **Read-twice-and-compare** consensus mode (optional, ~2× cost) for maximum reliability on hard receipts — discussed in R3, deferred.
- **v0.3 — Advice** (budget vs actual, overspend nudges, insights feed).
