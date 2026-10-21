# Decisions

*Each entry is **Problem → Evidence → Decision → Result**. Evidence comes from real testing in [feedback-notes.md](feedback-notes.md) or from the design constraints in [problem-statement.md](problem-statement.md). This is the record of *why* the product is the way it is.*

Legend for Evidence source: `[design]` = decided up front from the problem; `[R1]` = Round 1 testing (2026-10-12); `[R2]` = Round 2 (2026-10-13); `[R3]` = Round 3 (2026-10-15); `[R5]` = Round 5 (2026-10-18); `[R6]` = Round 6 (2026-10-19); `[req]` = a direct user requirement raised during use; `[eng]` = an engineering decision made while building a milestone.

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

## D22 — Bank statements import from PDF as well as CSV `[req]`

- **Problem:** Reconciliation assumed a CSV export (D2), but some banks only hand the customer a **PDF** statement — leaving a user who can't get a CSV unable to reconcile.
- **Evidence (req):** Raised directly while preparing to test reconciliation — "accept a PDF too, in case I can't get a CSV."
- **Decision:** Keep CSV as the primary path; add a PDF fallback that ends in the **same normalized rows**, so reconciliation/exceptions/close are unchanged. The backend extracts the PDF's text deterministically (`pdfplumber`), then structures it into transactions with gpt-4o — which only *reads*; every amount is re-parsed and **signed in code** (negative = money out) and every date re-parsed to ISO, consistent with D1. A deterministic regex parser (leading date + trailing signed amounts, honouring `(123,45)` / `123,45-` / European `1.234,56`) is the offline/mock path and the safety net if the model call fails. A **scanned/image-only PDF** (no text layer) is rejected with a clear "upload a CSV, or a text-based PDF" message — we don't guess at pixels here.
- **Result:** A text-based PDF statement imports and reconciles like a CSV. Verified end-to-end on a synthetic multi-row statement (5 rows incl. a parenthesised negative and a `2.000,00` credit, with the opening-balance/header/footer lines correctly ignored). *(Remaining real-test step: import an actual bank PDF through the UI with gpt-4o configured.)*
- **Follow-up (same session):** real CSV testing surfaced that a bank export whose date column wasn't literally named `date` wrote an empty string to the DB and returned an unhandled 500 — which the browser reported as "Can't reach the backend" (the 500 carried no CORS headers). Fixed by (a) **auto-detecting** the usual column names across EN/PT/ES/DE exports and sniffing the delimiter, (b) never writing an unparseable date — returning a clear message naming the file's headers instead, and (c) returning import failures as proper 400/502 responses so the real cause shows in the UI. Verified live: a `;`-delimited Portuguese-header CSV with no mapping imported 2 rows correctly. Also added an **optional free-text "note for the extractor"** on the receipt and import dialogs — a user hint appended to the extraction/structuring prompt to resolve ambiguity, with the model still instructed to read printed figures and never invent values (consistent with D1). Unit tests cover the heuristic, normalization, column auto-detect and the empty-date guard (90 passing).

## D23 — Top-ups and transfers aren't purchases, so they don't need a receipt `[req]`

- **Problem:** A real Revolut statement mixes card purchases with account **top-ups** (money in from the user's other card) and **person-to-person transfers**. The reconciliation engine flagged every unmatched bank line as "missing a receipt", so these non-purchases cluttered the exceptions list with false problems.
- **Evidence (req):** On the user's October export, 21 of 41 rows were top-ups/transfers between his own accounts or to people — "these don't need a matching receipt." (Same spirit as [D3](#d3--cash-is-counted-but-excluded-from-reconciliation-design): only things that *should* match are checked.)
- **Decision:** A bank line is **reconcilable** (expected to match an expense/receipt) only when it's money **out** AND not a top-up / transfer / currency exchange / ATM withdrawal — detected from the statement's `Type` column (Revolut and similar) or, failing that, the description. Non-purchases are still imported and counted toward the balance, but they're excluded from both the match candidates (so a transfer can't be falsely matched to a receipt by amount+date) and the "unmatched / missing receipt" exceptions. Incoming credits (amount ≥ 0: top-ups, salary, refunds) are non-reconcilable by definition.
- **Result:** On the real statement this leaves **20 card purchases** that legitimately want a receipt and silently excludes **8 top-ups + 13 transfers** — the exceptions list stays trustworthy (extends D3 from "cash" to "non-purchase bank movements").

## D24 — Imported statements are first-class; the exceptions view collapses to one row per file `[req]`

- **Problem:** Importing a statement dropped dozens of individual "bank payment with no receipt" rows straight into the dashboard and Reconciliation exceptions — overwhelming, with no way to see a statement as a whole (what it covers, its total, which payments still need a receipt).
- **Evidence (req):** After importing the 41-row October Revolut file, the exceptions list filled with one row per unmatched card payment — "you get lost there." The user asked for a single row per imported file, clickable through to a dedicated **Bank statements** section showing the file's period, total, and its transactions, with a **New** marker like the exceptions highlight.
- **Decision:** Model an imported file as a `bank_statements` row (filename, source type, upload date, period, money in/out/net) with `statement_id` on each `bank_transaction`. A new **Bank statements** page lists every statement and drills into its transactions (each tagged Matched / Needs receipt / Not a purchase — see [D23](#d23--top-ups-and-transfers-arent-purchases-so-they-dont-need-a-receipt-req)); statements are deletable. In the dashboard and Reconciliation exceptions, the many unmatched-bank rows **collapse into one row per statement** (with a live "N payments still need a receipt" count), scoped to the month on screen, linking into the section; a just-imported statement shows **New** until opened.
- **Result:** The October import now shows as a single row ("20 payments still need a receipt · 2 Oct – 18 Oct · 41 transactions") instead of 20 separate lines; the detail view shows all 41 transactions with their status. Verified end-to-end in the browser (0 console errors).

## D25 — Reconciliation is a hand-drivable workbench; online payments can opt out `[req]`

- **Problem:** Auto-matching alone isn't enough — some real pairs differ by a few cents or days and won't auto-match, and some bank payments (online/digital purchases) will *never* have a receipt, so they'd nag forever as "unmatched."
- **Evidence (req):** On the real Revolut statement, the Uber Eats receipt (€18.39, after a loyalty discount) and the bank charge (€16.14) are the same purchase but differ in amount; and payments like tropsunprod.com / Steam / fal.ai have no receipt at all.
- **Decision:** Running reconciliation opens a **results popup** that is also a workbench: it lists matched receipt↔bank pairs (each with *View receipt* and *View transaction* — the bank line's exact CSV row), the unmatched expenses with a **suggested** bank candidate, and the bank payments still needing a receipt. The user can **match**, **unmatch**, reject a suggestion (**Not a match** → the expense stays pending, the next candidate is offered), and mark a bank line **No receipt** (an acknowledged online payment that leaves the reconciliation cycle — it's no longer flagged and never offered as a candidate, extending [D3](#d3--cash-is-counted-but-excluded-from-reconciliation-design) from cash to online payments). A **Match manually** button opens the same view without running the auto-matcher. Suggestions are only offered when **believable** — the same vendor, or an exact amount within a few days — never a random closest-by-amount line.
- **Result:** Reconciliation went from a one-shot auto-pass to a view the user can drive by hand and trust: the Uber Eats discount case is matched in one click, online payments drop out of the cycle, and no nonsensical pairings are suggested. Manual links persist (`POST /reconcile/match` · `/unmatch` · `/no-receipt`, `GET /reconcile/state`).

## D26 — A measured extraction-accuracy number, from a labelled eval set `[R5]`

- **Problem:** The README claimed extraction "works on upright photos" but had no number behind it. Without a repeatable measure, we couldn't tell whether a change (prompt, model, rotation logic) actually helped or which field was the weak spot.
- **Evidence (R5):** Picking a model or tuning a prompt by eyeballing one upload is guesswork; a product-engineering claim needs a figure that can be re-run.
- **Decision:** Build an eval harness (`backend/scripts/eval_extraction.py`) that runs the **shipped** pipeline — the vision read **plus** the deterministic VAT/amount/category logic — over a hand-labelled set of real receipts and scores each field (vendor, date, total, VAT amount, VAT rate, category). Per-image reads are cached so re-runs are free; the real receipts and labels stay local (git-ignored, personal data), and only an aggregate table is published to `backend/eval/RESULTS.md` (the README "Results" number). Currency is deliberately not scored (receipts print a € symbol, not the ISO text).
- **Result:** A reproducible accuracy figure with an honest per-field breakdown. It immediately earned its keep: it surfaced the Uber-Eats→Transport categorization gap, quantified the rotated-photo weakness, and **drove the model choice in [D27](#d27--vision-model--gpt-5-mini-a-reasoning-model-that-reads-dense-vat-tables-r5)** (gpt-4o 84% → gpt-5-mini 93%).

## D27 — Vision model = gpt-5-mini, a reasoning model that reads dense VAT tables `[R5]`

- **Problem:** On a real 3-rate Continente receipt (6/13/23%, total €10.89) the ledger showed only two rates with amounts fudged to hit the total, and the bag line was misread — it looked like the app was "guessing numbers to make the total work."
- **Evidence (R5):** Diagnosis (per-model, full-res) showed it wasn't a logic bug — the pipeline correctly *rejected* the mis-tied table and routed to review. The cause was the model's eyesight: **gpt-4o (and gpt-4.1, gpt-4o-2024-11-20) consistently mis-read or scrambled the per-rate amounts** in the dense IVA summary table. The **gpt-5-mini / o4-mini reasoning models read the same table perfectly** (6→5.03, 13→5.76, 23→0.10). The eval confirmed it across the set: **84% → 93%** overall, VAT amount/rate ~67%/56% → ~89%/89%.
- **Decision:** Switch receipt reading to **gpt-5-mini**; the OpenAI call path auto-detects reasoning models (`gpt-5*`/`o*`) and uses `max_completion_tokens` with budget for their reasoning step. Two supporting fixes for hard photos shipped alongside: the auto-rotation now **reads every orientation** (incl. 180°) and keeps the most *complete* read, instead of stopping at the first plausible one (a sideways read can look confident on a fragment); and the "retake this photo" prompt now **trusts a read that reconciles to the cent** over the model's self-reported confidence, so a correct read with modest confidence no longer nags a retake (it still goes to review for a quick confirm).
- **Result:** The 3-rate receipt now reads all three rates correctly. Trade-off accepted: gpt-5-mini is slower (~20s/read vs ~6s). The hardest photo in the set — crumpled **and** rotated **and** dark — can still mis-read and is routed to review, which is the design. *(A `claude-opus-4-8` comparison is pending Anthropic API credits.)*

## D28 — "No bank line": a card expense can opt out of reconciliation `[R5]`

- **Problem:** In the reconciliation results, rejecting the wrong suggestions ("Not a match") left the unmatched-expenses list never reaching a clean state — there was no way to say "this expense simply has no bank line."
- **Evidence (R5):** Several real card expenses (restaurant receipts, a twice-uploaded Pingo Doce) have no corresponding line in the imported Revolut statement. "Not a match" only rejects one *suggestion*; the bank side already had **No receipt** to drop a line out of the cycle, but the expense side had no mirror.
- **Decision:** Add the expense-side mirror — a **No bank line** button on each unmatched expense (backed by a `no_bank_match` flag and `POST /reconcile/no-bank-match`). An acknowledged expense leaves the Unmatched list and the reconciliation cycle (not flagged as an exception, not offered for matching); it's reversible, and matching it later clears the flag. Extends [D25](#d25--reconciliation-is-a-hand-drivable-workbench-online-payments-can-opt-out-req) from the bank side to the expense side.
- **Result:** The Unmatched section can now actually reach a clean/empty state — the user clears the expenses that genuinely have no bank match, instead of staring at them forever.

## D29 — A duplicate is the same vendor + total, not the same date `[R6]`

- **Problem:** Two ledger rows were obviously the same Pingo Doce receipt (same €48.24), yet duplicate detection never flagged them — one re-uploaded over the other, both posted.
- **Evidence (R6):** The upload-time check ([D13](#d13--flag-duplicates-at-upload-before-they-post-r2)) keyed on **vendor + amount + *exact date***. But the two reads disagreed on the date (2026-10-08 vs 2026-10-03) *and* on the vendor string (`Pingo Doce` vs `Pingo Doce - PD Olaias`) — the model reads both fields inconsistently across two photos of one receipt. The date is in fact the single most-misread field (it has its own repair logic, [D16](#d16--deterministic-date-year-repair--focused-re-read-r3)), so requiring an exact date to catch a duplicate is backwards: a real duplicate will often have a *different* date precisely because of a misread.
- **Decision:** Fingerprint a duplicate on the **strong, stable fields** — the **vendor** (matched by *brand prefix*: one name's leading tokens are a prefix of the other's, so `Pingo Doce` ≡ `Pingo Doce - PD Olaias`) and the **total to the cent** — within a **±30-day window** rather than an exact date (and vendor+total alone when either date is unreadable). The matching logic is a pure, unit-tested helper (`repository.match_duplicate_rows`). The image itself can't be the automatic key — two photos of one receipt differ in pixels, and two different receipts can look alike — so the existing **compare-both-receipts-and-decide** popup ([D13](#d13--flag-duplicates-at-upload-before-they-post-r2)) remains the human source of truth. Supersedes the exact-date/exact-vendor match in D13; the human-confirm gate (route to review, never auto-post a suspected duplicate) is unchanged.
- **Result:** Re-uploading the same receipt now routes to review as a possible duplicate even when the date or vendor reads differently (verified against the live ledger for `Pingo Doce`, `PINGO DOCE`, and the branch form, while a different vendor / far-off date / different amount correctly do not match). **Honest limit:** a genuine repeat purchase that rings up to the identical cent within 30 days is also flagged — and dismissed in review — which is the safe direction to err.

## D30 — Measure, observe and validate the LLM layer, don't just assert it `[eng]`

- **Problem:** The extraction pipeline *claimed* accuracy and *had* guardrails, but three things working LLM systems rely on were missing: nothing measured whether the guardrails actually catch bad reads; no call was observable (latency, tokens and cost were read from the SDK response and thrown away); and the model's JSON was parsed ad-hoc with no schema validation or retry.
- **Evidence (eng):** A system you operate has to answer *"what happened on that read, and did the safety net hold?"* — and *"is a change (prompt, model) actually helping?"* Eyeballing one upload can't. The existing eval scored field accuracy but never ran the gate, so the guardrails' real-world effectiveness was unknown.
- **Decision:** Add three layers, each built to stay honest and self-contained.
  1. **Validated structured output** — the extraction parses through **Instructor** (`response_model=ExtractionResult`, `instructor_max_retries`), so malformed output is re-prompted against the schema; on any failure it falls back to the previous tolerant JSON parse and records `fell_back` on the trace. The prompt is unchanged, so this can only hold or improve accuracy.
  2. **Self-contained observability** — every call is timed and its tokens/estimated cost captured (`services/llm_trace.py`) and persisted to an `llm_traces` table (services stay DB-free; the router persists). A **Model & Evals** page surfaces accuracy, guardrail effectiveness, confidence calibration and live latency/cost/outcome per read. **LangSmith** tracing + a dataset/experiment script are available but strictly **opt-in** behind an env flag, so the app and the eval never depend on a hosted service.
  3. **One gate, measured** — the routing logic was factored out of the `/extract` endpoint into a pure `services/gating.decide_gate`, called by **both** the endpoint and the eval harness. The eval now runs the *shipped* gate over the labelled set and reports **false-auto-post rate**, **over-review rate** and **confidence calibration** (`services/eval_metrics.py`).
- **Result:** Instructor lifted the eval from **93% → 98%** overall (10/11 receipts fully correct). The guardrail metrics immediately earned their keep with honest findings: on the set the one wrong read — a date off by a single day that otherwise reconciles — **auto-posted** (no guardrail can detect a plausible, self-consistent wrong date), and **70% of correct reads were sent to review** because the gate trusts a **poorly-calibrated** confidence score (reads at 0.7–0.8 were 100% correct, 0.8–0.9 only 75%). That quantifies the deferred question in [D21/D27](#d27--vision-model--gpt-5-mini-a-reasoning-model-that-reads-dense-vat-tables-r5) — *should a cent-perfect reconciling read auto-post?* — with data, rather than leaving it to intuition. Every read now carries a real latency/token/cost number.
- **Follow-up (day 8, 2026-10-20) — the opt-in LangSmith path was shipped but never actually fired.** With
  `LANGSMITH_TRACING=true` set, no trace ever reached LangSmith. Two causes, both environmental, not logic: (1)
  pydantic's `env_file` only populates the `Settings` object, but the LangSmith SDK and `llm_trace.langsmith_enabled()`
  read `os.environ` directly — so the `LANGSMITH_*` vars were invisible to them; (2) the LangSmith client is
  `requests`-based and this Python build had no usable CA bundle, so even once enabled its TLS calls would fail
  (OpenAI/Supabase use httpx, which bundles certifi, so they were unaffected — which is exactly why *only* LangSmith
  was broken and it went unnoticed). Fixed in `config.py` by loading `backend/.env` into `os.environ` at import and
  pointing `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` at `certifi.where()` (both idempotent; never override an operator's
  existing value). Verified end-to-end: the `Receipt-Ghostbuster` project **auto-created on the first trace** (proof
  nothing had ever landed), and an Experiment ran over the 11-receipt dataset. Lesson (reinforces the authenticity
  rule): a feature that *compiles and is wired* is not a feature that *works* — an opt-in integration has to be
  switched on and watched reach its destination, or the "optional LangSmith" claim is unverified. 128 tests unchanged.

## D31 — Choose the reading model with a multi-axis comparison, and measure accuracy by receipt type `[eng]`

- **Problem:** The eval measured a single model as one aggregate number. Two blind spots followed: (1) the current model choice (gpt-5-mini) rested on a one-off accuracy check in [D27](#d27--vision-model--gpt-5-mini-a-reasoning-model-that-reads-dense-vat-tables-r5), never reproducible or weighed against **latency and cost** — the axes that actually decide a production LLM pick; and (2) a 98.4% average could hide a weak receipt *type* (e.g. rotated photos reading worse than flat ones) with no way to see it.
- **Evidence (eng):** Picking a model on accuracy alone, from one eyeballed run, isn't a decision you can defend or re-verify; and an aggregate that can't be sliced can't prove the hard cases (multi-rate VAT, rotation) actually work.
- **Decision:** Three additions, all reusing the existing harness so a model is scored identically to the canonical run.
  1. **Multi-model comparison** (`scripts/eval_models.py`) runs the shipped pipeline across models and writes an **accuracy × latency × cost** matrix (plus per-slice) to committed `backend/eval/MODELS.md` / `models.json`. It captures each read's observability trace (latency/tokens/cost), which the single-model harness discards. `RESULTS.md`/`metrics.json` stay the canonical **single shipped model** the in-app page serves. A fairness fix shipped alongside: an `anthropic_max_tokens` setting (default 4096) raises the old hard-coded 1024 output ceiling so a Claude model isn't truncated mid-JSON on a dense multi-rate receipt (the OpenAI path already bumped reasoning models to 8000).
  2. **Accuracy by receipt type** — an optional `tags` array on each label (rotated / multi_rate / discount / payment_only / …) drives a shared, unit-tested `eval_metrics.slice_accuracy`; the by-type table lands in `RESULTS.md` and under `slices` in `metrics.json`.
  3. **LangSmith per-model experiments** — `scripts/langsmith_eval.py` takes `--provider/--model`, so each model is its own Experiment for the LangSmith compare view (opt-in, otherwise unchanged).
- **Result (real run, 20 labelled receipts, 2026-10-21):** **gpt-5-mini 98.2%** · **gpt-4o 94.5%** · **claude-haiku-4-5 87.3%** · **claude-opus-4-8 98.2%** (the canonical single-model pass in `RESULTS.md` scores gpt-5-mini **99.1%** — it and the comparison are *independent* read passes of a non-deterministic reasoning model, ~1pp, within the n=20 noise). The set grew **11→20** on fresh user-supplied ground truth. The spread is mostly **VAT** (vat_amount 100% / 81.2% / 75.0%), reproducing D27's "gpt-4o mis-reads dense multi-rate VAT tables" at the **slice** level (`multi_rate` 98.6% / 91.7% / 88.9%); **rotation** is the slice where the cheap model collapses (gpt-5-mini & gpt-4o both **94.7%**, **Haiku 57.9%**). New hard cases the chosen model handled cleanly: a 41%-off **discount** receipt (100%) and a **crumpled** Pingo Doce (100%). Latency/cost unchanged in shape: gpt-5-mini is the **slowest** (avg 36s vs gpt-4o 7s / Haiku 10s) yet the **cheapest per read** ($0.0083 vs $0.0194 / $0.0118) **and the most accurate** — accuracy *and* cost favour it, only latency favours the others. **The Opus 4.8 column (now run) is the decisive cost finding:** Opus **ties** gpt-5-mini on overall accuracy (98.2%) — cleaner on date (100%) and upright (100%) but *weaker* on rotated (89.5% vs 94.7%) — yet costs **$0.32/read vs $0.0083** (≈**39×**; $6.40 vs $0.17 for the 20-receipt run). The premium model buys nothing here, so **gpt-5-mini stays the pick on accuracy *and* cost**. The per-model runs were also pushed to **LangSmith** as separate Experiments (gpt-5-mini / gpt-4o / Haiku) for the hosted compare view. **Honest caveat (in `MODELS.md`):** n=20 is still small — differences of a few points are not statistically significant. 130 tests pass.
- **Process note — the eval caught a bad _label_, not a model bug.** The first 20-receipt run showed every model "failing" a rotated tobacco receipt (no VAT + "Uncategorized"). On inspection the receipt **prints no VAT and nothing identifying it as tobacco** — "tobacco / 0%" was the *labeller's* outside knowledge, not on the paper. So the model was **correct** to not invent it (reads never guesses, [D1](#d1--the-ai-is-never-trusted-blindly-design)); the **label** was wrong. Corrected to score only what the receipt shows (like the other viva.com payment-only receipt), which lifted gpt-5-mini **95.6% → 98.2%** and reinforced the principle — the right UX is exactly what the app already does: print nothing → don't guess, the user adjusts in review ([D18](#d18--estimated-vat-from-product-type-when-the-receipt-prints-none-r3)). Lesson: an extraction label must encode what's **extractable from the receipt**, never the labeller's private knowledge — the same poison the authenticity rule guards against on the model side.
- **Deferred (next eval round):** a per-model structured-output reliability taxonomy (retry/schema-failure breakdown beyond the `fell_back` count already shown), an accuracy-regression CI gate against a committed baseline, and a **calibrated** LLM-as-judge (validated against human labels) for the semantic fields and the future chatbot's free-text answers.

---

## Planned (decided, not yet built)

- **Auto-post a cent-perfect reconciling read** — the eval ([D30](#d30--measure-observe-and-validate-the-llm-layer-dont-just-assert-it-eng)) shows the confidence gate over-reviews correct reads because confidence is poorly calibrated; letting a read that reconciles to the cent auto-post would cut that friction. Deferred (risk: a self-consistent-but-wrong read auto-posting), now measurable.
- **Read-twice-and-compare** consensus mode (optional, ~2× cost) for maximum reliability on the hardest (crumpled + rotated) receipts — discussed in R3/R5, deferred.
- **Model comparison is now 4-wide** ([D31](#d31--choose-the-reading-model-with-a-multi-axis-comparison-and-measure-accuracy-by-receipt-type-eng)) — gpt-5-mini, gpt-4o, Haiku 4.5, **Opus 4.8** (Opus ties gpt-5-mini at ~39× the cost, so no model change). Further columns (e.g. Sonnet 5) are one command each.
- **Next eval round** — per-model structured-output reliability taxonomy, an accuracy-regression CI gate vs a committed baseline, and a calibrated LLM-as-judge for semantic fields + the v0.5 chatbot.
- **v0.4 — Advice** (budget vs actual, overspend nudges, insights feed).
