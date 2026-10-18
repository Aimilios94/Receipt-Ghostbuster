# Changelog

All notable changes to Receipt Ghostbuster. Format based on [Keep a Changelog](https://keepachangelog.com).
The *why* behind changes lives in [DECISIONS.md](DECISIONS.md).

## [0.2.4] — 2026-10-18

Bank statements & a hand-drivable reconciliation workbench, from the Round 4 testing session on a real **Revolut** export and real receipts (see [D22–D25](DECISIONS.md), [feedback-notes Round 4](feedback-notes.md)). Backend tests **80 → 97 passing**.

### Added
- **Replace a receipt's photo (Edit) from anywhere it's shown** — next to every **View receipt** button (reconciliation results, the expense-detail popup, dashboard drill-downs) there's now an **Edit** action. It opens the photo picker, uploads a new photo of that receipt, stores the straightened image in place of the old one, and **re-reads it** — refreshing the amount / VAT / vendor / date / category / line items when the new photo reads cleanly (if it can't be read, the image is replaced but the existing figures are kept, so a bad re-shot never wipes good data). New `POST /expenses/{id}/rescan`; the extraction field logic is shared with `/extract` via `services/receipt_fields.py`.
- **Reconciliation results popup** — running reconciliation now opens a popup that shows each **receipt ↔ bank transaction** match one by one (with **View receipt** and the exact statement transaction it matched), the **card expenses with no bank match**, and the **bank payments still waiting for a receipt**. The summary figures (Matched / Unmatched expenses / Bank without receipt) are **filter tabs**. Each unmatched expense is shown next to its **most likely bank candidate** with a central **Match →** button and a fit note (e.g. "Δ€0.38 · 12d apart") — so near-matches that differ only by date are one click to confirm — plus an **Others** picker for the rest (ranked by amount then date). Any match can be **unmatched**. All persisted via new `POST /reconcile/match` · `/reconcile/unmatch` and a `GET /reconcile/state`.
- **"Not a match"** next to the suggested **Match →** — rejects a wrong suggestion so the expense stays unmatched and the next **plausible** bank candidate is offered (or "No likely match", still pending).
- **Suggestions are now only offered when there's a real reason** — the **same vendor**, or an **exact amount within a few days** (e.g. a payment-gateway name vs the merchant). A merely close amount on an unrelated vendor is never suggested — those rows read "No likely match · stays pending" instead of showing a random bank line. The **Others** picker (opt-in) still lets you force any link by hand.
- **Mark a bank payment as "No receipt"** — an online/digital payment you'll never have a receipt for (e.g. a web purchase, a fee) can be acknowledged from the results popup; it then leaves the reconciliation cycle entirely (no longer flagged "needs a receipt", never offered as a match candidate, and shown as "No receipt" in the statement detail). Backed by a `no_receipt` flag on `bank_transactions` and `POST /reconcile/no-receipt`.
- **"Match manually" button on the Reconciliation page** — opens the same match / unmatch / results view **without** running the auto-matcher first (via `GET /reconcile/state`), so you can do and undo matches by hand any time.
- **View transaction** on every bank line — the counterpart of View receipt. It opens the exact statement row (date, amount, balance, source file, and every original CSV column: Type, State, Started/Completed Date…), so a bank payment is as inspectable as a receipt.
- **"Transactions detailed" header** in the statement popup, separating the Spent/Received/Net/Period summary from the transaction list.
- **Bank statements section** ([D24](DECISIONS.md)) — a new page (and sidebar item below Reconciliation) listing every imported statement file: name, CSV/PDF, upload date, the period it covers, and its **Spent / Received / Net** totals. Click a statement to see all its transactions, each tagged **Matched / Needs receipt / Not a purchase**; statements are deletable (cascades to their transactions and unlinks any matched expenses). Backed by a new `bank_statements` table + `statement_id` on `bank_transactions`.
- **One row per import in the exceptions view** — instead of flooding the dashboard and Reconciliation with every unmatched bank payment one-by-one, each statement now collapses into a single row ("octomber-2026.csv — 20 payments still need a receipt · 2 Oct – 18 Oct · 41 transactions"). **Clicking the row** opens its transactions popup in place (no navigation); the **View** button goes to the Bank statements section without auto-opening a popup. A freshly-imported statement is flagged **New** until opened (localStorage, like the exceptions highlight). The collapsed rows are scoped to the month on screen.
- **Statement transactions popup is centered and scrollable** — the transactions are laid out in a responsive two-column grid (not one long vertical list) inside a wider modal that's capped to the viewport height and scrolls internally, so a 40-row statement stays fully on screen. (Modals app-wide now cap their height and scroll their body instead of running off the screen.)
- **Bank-statement PDF import** ([D22](DECISIONS.md)) — the Import dialog now accepts a text-based **PDF** as well as a CSV, for when a bank only offers PDF statements. The backend extracts the text with `pdfplumber`, structures it into transactions with gpt-4o (reading only — every amount/date is re-parsed and signed in code), and falls back to a deterministic regex parser offline. Both formats produce the same normalized rows, so reconciliation is identical. Scanned/image-only PDFs are rejected with a clear "upload a CSV instead" message rather than guessed at.
- **Optional "note for the extractor"** on both the Snap-a-receipt form and the Import-statement dialog — a free-text hint the uploader can add (e.g. "the date is handwritten at the top", "this is a fuel receipt", "dates are DD-MM-YYYY"). It's appended to the receipt-extraction prompt and to the PDF-statement structuring prompt to resolve ambiguity, while the model is still told to read printed figures and never invent values.

### Fixed
- **Receipt totals stay internally consistent when a printed VAT line is slightly misread.** Previously, if the printed IVA summary's gross missed the total by more than 5 cents (a crumpled digit, e.g. 13,31 read as 13,11), the authoritative table was dropped and the figures fell back to the model's item lines — which, on a hard receipt, could sum to far less than the total (e.g. a Pingo Doce showing line items of €37.50 under a correct €48.24 total). The printed table is now accepted within a **relative** tolerance and its per-rate buckets are **scaled to the exact total**, so net + VAT + paid always reconcile (that Pingo Doce now reads Net €43.79 · VAT €4.45 · Paid €48.24). Applies to both new uploads and receipt re-scans.
- **Bank CSV import no longer fails on a non-standard date column.** It now **auto-detects** the usual column names (date / amount / description / balance, plus debit/credit) across English & Portuguese/Spanish/German exports and sniffs the delimiter (`,` / `;` / tab), so a standard bank export imports without any manual mapping. An unreadable or blank date is never written to the database (which previously produced a `invalid input syntax for type date: ""` 500); instead the import returns a clear message naming the CSV's actual headers.
- **Revolut exports import as-is** — recognises `Completed Date` / `Started Date`, strips the time component from a `D/M/YYYY HH:MM` timestamp, reads quoted European decimals (`"-11,58"`), and **skips not-yet-settled rows** (`PENDING` / `REVERTED` / etc. via a `State`/`Status` column) so they don't become false unmatched exceptions. Verified on a real 44-row October statement → 41 settled transactions imported.
- **Top-ups, transfers and incoming credits are no longer flagged as "missing a receipt."** Reconciliation now treats a bank line as a purchase only when it's money *out* and not a top-up / transfer / exchange / ATM (detected via the statement's `Type` column, e.g. Revolut, or the description). Account top-ups and person-to-person transfers are still imported and counted, but they never appear as unmatched exceptions and can't be falsely matched to a receipt. On the real statement this left **20 card purchases** needing receipts and excluded **8 top-ups + 13 transfers**.
- **Server errors now surface the real message in the browser.** A failed import used to read as "Can't reach the backend" because the unhandled 500 carried no CORS headers; import errors are now returned as proper 400/502 responses with the actual cause.
- **Transient socket errors under concurrent load, gone.** A heavy request (reconciliation, which makes many Supabase calls) running at the same time as the UI's refetches could trip a Windows `WinError 10035` on the shared Supabase client and flash "can't reach the backend". The Supabase client is now created per worker thread (no cross-thread contention) and the frontend retries transient failures, so reconciliation runs cleanly.
- **Long popups no longer run off the screen** — every modal is capped to the viewport height and scrolls its body, staying centered.

Backend tests **80 → 90 passing**.

## [0.2.3] — 2026-10-15

Extraction robustness & review UX, from the Round 3 testing session on a batch of hard real receipts (3-rate, discounted, no-VAT, sideways, crumpled). See [D14–D21](DECISIONS.md) and [feedback-notes Round 3](feedback-notes.md). Backend tests **53 → 80 passing**.

### Added
- **LLM-assisted categorization** ([D15](DECISIONS.md)) — gpt-4o suggests a category during extraction; rules run first, the suggestion fills unknown vendors (Continente / PD OLAIAS / Pingo Doce → Groceries), validated against the real category list. New **Tobacco** category; new `POST /expenses/{id}/category` + an **editable Category dropdown in the Ledger**.
- **Printed VAT summary table as the VAT source of truth** ([D14](DECISIONS.md)) — extraction transcribes the IVA summary (`tax_lines`) and uses it (not re-derived item math) when it ties to the total; prompt forbids guessing/adjusting figures.
- **Estimated VAT when none is printed** ([D18](DECISIONS.md)) — standard Portuguese rates suggested per product (food 13% / drinks 23% / groceries 6%), computed in code, routed to review and shown as **amber "suggested"** VAT fields with a tooltip (cleared once edited). A real 0% is a captured answer.
- **Server-side auto-rotation** ([D20](DECISIONS.md), Pillow) — EXIF orientation + landscape detection + re-read at 90°/270°/0° (180° fallback), keeping the best-reconciling orientation; the straightened image is stored.
- **Date re-read + year-repair** ([D16](DECISIONS.md)) — a focused date-only second pass and a deterministic year-correction (snaps a misread year to the recent one, never the future) that forces review with a "corrected X→Y, confirm" note. Recognises `Data Emissão` ISO dates and the `YY-MM-DD` terminal line.
- **Self-consistency guardrail + retake** ([D21](DECISIONS.md)) — an unreliable read (printed VAT table vs item lines disagree per-rate) no longer auto-posts; a **retake prompt** at upload and a **Retake photo** button in the review queue re-read a clearer shot.
- **Duplicate-at-upload comparison popup** — side-by-side cards (new upload vs each ledger match) with Net/VAT/Total and View-receipt, plus Discard / Keep.
- **Reconciliation exceptions are interactive** — clickable → full expense detail (Net · VAT · Total · rate · date · receipt), **deletable** (dashboard + Reconciliation page), sorted **newest upload first**, with an unread **"NEW"** highlight that clears on open.

### Changed
- **Discounts are modelled, never products** ([D17](DECISIONS.md)) — POUPANÇA / Special Offer / Desconto / negatives are excluded from line items; `total` is the amount **paid after** discount; a discounted receipt's lines are scaled to the amount paid so VAT is computed on what was paid.
- **Amount paid = net + VAT** ([D19](DECISIONS.md)) — when the model reads the net/BASE line as the total, the gross is stored instead (fixed Auchan €3.77 → €4.18).
- **Ledger columns are now Net · VAT · Total** (was Amount · VAT), footer and the exception-detail popup too (labelled **Net (total) · VAT (total) · Paid**).
- Review/ledger **VAT-line editor** shows per-line **net · VAT · total**, the Amount field is the editable **full amount paid** (with a reconcile hint), and **0%** is promoted in the rate picker.
- Orientation-first extraction prompt (locate the store name at the top before reading); per-line **quantity** captured.

### Fixed
- **0% / exempt receipts (e.g. tobacco) no longer flagged "missing VAT"** in reconciliation — only a truly-unknown VAT (both rate and amount absent) is flagged; confirming a receipt as 0% clears it.
- Hallucinated/confident-wrong reads on crumpled receipts no longer auto-post (caught by the consistency guardrail).

## [0.2.2] — 2026-10-13

Per-line VAT + Round 2 testing fixes — real accounting rigor for mixed-rate receipts, duplicate-at-upload, and ledger/editing ergonomics (see [D12](DECISIONS.md#d12--per-line-vat-a-receipt-can-hold-multiple-rates-design--r2), [D13](DECISIONS.md#d13--flag-duplicates-at-upload-before-they-post-r2), [feedback-notes Round 2](feedback-notes.md)).

### Added
- **`expense_line_items` table** — each itemized line stores its own VAT rate, so a single receipt can hold multiple rates (e.g. 6% food + 23% other) instead of being flattened to one dominant rate.
- Extraction now reads **per-line VAT rates**, including the Portuguese VAT-code + summary-table convention; line items are persisted and cascade-delete with their expense.
- `GET /expenses/{id}/line-items` and `GET /expenses/line-items`; `/extract` now returns `line_items` + a code-computed `vat_breakdown`.
- VAT-by-rate drill-downs (dashboard VAT card + Ledger footer) now **split a mixed-rate receipt across rates** and show a "mixed" indicator per row; expenses without line items fall back to their single stored rate.

- **Multi-rate VAT editor in the review queue** (from Round 2 testing on a real 3-rate Continente receipt) — add one VAT line per rate (description, € gross, rate 6/13/23/0), seeded from the extracted lines, with a **live per-rate breakdown** and the amount auto-synced to the lines' total. The confirm endpoint stores the lines and sums VAT per rate.
- **Click a Ledger row → expense detail** (`ExpenseDetailModal`): the VAT categorized per rate, the itemized line items (amount + rate + VAT each), and the receipt image — for any row, including those surfaced by the duplicates filter.
- **Receipt thumbnail column** in the Ledger (after Status) — a click opens the full receipt image.
- **Post confirmation toast** now states what landed: *"Posted CONTINENTE — €11.58 incl. €1.00 VAT added to your ledger"* (was a bare "Posted"), so you don't have to open the Ledger to confirm.
- **Change status from the Ledger** — the Status column is a dropdown (Posted / Needs review / Confirmed) backed by a new `POST /expenses/{id}/status`; move a posted row back to review in one click.
- **Edit from the dashboard drill-downs** — every expense row in a drill-down (e.g. Spending by category) has an **Edit** action (`ExpenseEditModal`) to fix vendor/date/category and the per-rate VAT lines, reusing the same multi-rate editor.

- **Duplicate detection at upload** (D13) — `/extract` flags a receipt that matches an existing ledger row (same vendor + amount + date), forces it to the review queue instead of auto-posting, and shows an in-modal warning naming the existing expense.
- **Expense detail totals** — the Ledger row-detail now has a line-items total row and a grand-total strip (amount · incl. VAT · net).

### Removed
- Cleared the Phase-1 sample seed expenses from the working dataset so the ledger shows only real uploads (reload anytime with `scripts/load_sample_data.py`).

### Simplified
- The review Edit form dropped the redundant single "VAT rate" field; **all VAT now lives in the VAT-lines editor** (seeded with one line for single-rate receipts), so there's one consistent way to set VAT. The amount is always the sum of the lines.

### Changed
- A receipt's stored `vat_amount` is now the **sum of its per-rate VAT** (computed in code) when lines carry rates; the dominant rate is kept for the single-rate display.
- VAT per rate is computed **bucket-first** (VAT on each rate's gross total, split once) so it matches the printed Portuguese IVA summary to the cent — fixes a per-line €0.01 rounding drift.
- Extraction prompt reads the **top `DD/MM/YYYY` invoice date** as primary and ignores the bottom card-terminal `YY-MM-DD` line (fixes a real "date in the future" misread, extends D7).
- Backend tests: **53 passing** (added per-line VAT / breakdown / bucket-rounding coverage).

> Verified end-to-end against live Supabase: the real 3-rate Continente receipt (`1000017708.jpg`) reconciles to 6% €0.32 · 13% €0.66 · 23% €0.02 = €1.00, gross €11.58 — matching the printed IVA summary exactly. Remaining real-testing step: re-upload through gpt-4o with the fixed date prompt and confirm it auto-reads the 3 rates.

## [0.2.1] — 2026-10-12

Post-feedback UX & extraction improvements (from Round 1 testing — see [feedback-notes.md](feedback-notes.md)).

### Added
- Clickable **drill-downs** on every dashboard number (Total spent, VAT paid, Card & cash, Reconciled, each category row, and "See all") → the source expenses with receipt view (D10).
- **Per-rate VAT breakdown** in the VAT drill-down and a clickable VAT total in the Ledger footer (D-partial).
- **Delete** action on expenses in the drill-downs and the dashboard Ledger preview.
- **"Possible duplicate"** badge, row highlight, a "Possible duplicates" Ledger filter, and a deep-link from the duplicate exception (`Ledger?view=duplicates`) (D11).
- **View receipt** button and a **VAT rate (%)** field in the review Edit form.
- **Capture hint** on the snap screen (shoot flat, upright, good light) (D9).
- Product-engineering docs: `problem-statement.md`, `roadmap.md`, `DECISIONS.md`, `CHANGELOG.md`, `feedback-notes.md`.

### Changed
- Extraction prompt now reads **Portuguese day-first dates**, handles rotation, prefers the terminal date, and extracts every line item; OpenAI vision set to `detail:"high"` (D7, D9).
- `close`, `exceptions`, and `reconcile` now count **confirmed expenses only** — `pending_review` receipts stay off the ledger until posted (D8).

### Fixed
- Posting a reviewed receipt now updates Total spent, VAT, and exceptions (was a no-op) (D8).
- "Receipt from the future" false flag on clear receipts (caused by the old date prompt) (D7).

## [0.2.0] — 2026-10-04

Phase 2 — Refund Hunter.

### Added
- Subscription **detection** across bank + ledger (cadence, annual cost, stale flagging).
- **Refund Hunter** page: flag/keep/cancel/undo with a savings summary.
- **Draft cancel/refund emails** (LLM with deterministic template fallback), draft-only.
- **n8n → Gmail** draft delivery + weekly detection cron; `N8N_WEBHOOK_URL` config + `/health` reporting.
- OpenAI as an alternative vision provider.
- Deterministic extraction **guardrails** (`validation.py`); editable/deletable review queue; month-scoped exceptions.

### Fixed
- Review-queue "Post" sending an empty body (422); "Discard" now really deletes; ledger row delete.

## [0.1.0] — 2026-10-02

Phase 1 — Track & Reconcile (MVP).

### Added
- Receipt extraction via vision LLM + confidence gate; manual/cash entry.
- Rules-based categorization; VAT split computed in code.
- Bank CSV import; reconciliation engine (amount + date window + fuzzy vendor); cash excluded.
- Exceptions (unmatched, duplicate, amount-mismatch, missing VAT); monthly close.
- React + Vite frontend: Dashboard, Review queue, Reconciliation, Monthly close, Ledger.
- Supabase schema + RLS + receipts storage bucket; pytest suite; sample dataset.
