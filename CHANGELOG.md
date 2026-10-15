# Changelog

All notable changes to Receipt Ghostbuster. Format based on [Keep a Changelog](https://keepachangelog.com).
The *why* behind changes lives in [DECISIONS.md](DECISIONS.md).

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
