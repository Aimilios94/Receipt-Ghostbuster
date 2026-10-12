# Changelog

All notable changes to Receipt Ghostbuster. Format based on [Keep a Changelog](https://keepachangelog.com).
The *why* behind changes lives in [DECISIONS.md](DECISIONS.md).

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
