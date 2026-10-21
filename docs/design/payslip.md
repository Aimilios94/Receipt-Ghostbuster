# Design — Payslip tracking

*Status: design only (planned as v0.6). Nothing here is built yet. A short sketch to anchor the roadmap
entry; it reuses the receipt pipeline's shape wholesale.*

## Problem

"Where does my money go?" is only half the picture while income is a black box. A payslip shows what's
**taken before the money arrives** — income tax, social insurance, other deductions — and how that changes
month to month. Tracking it turns the app from an expense tracker into a fuller personal-finance view.

## Approach: same pipeline shape as receipts

- **Extraction** — the identical *vision-read-then-compute-in-code* pattern ([D1](../../DECISIONS.md)): the
  model reads the payslip; all arithmetic (net = gross − deductions, rate checks) is done in code and the
  numbers are reconciled, never trusted raw. A new field set: `gross`, `net`, `income_tax`,
  `social_insurance`, `other_deductions[]`, `period`, `employer`.
- **Review gate & guardrails** — reuse the confidence gate + deterministic checks; a payslip where
  gross − deductions ≠ net is routed to review, exactly like a receipt that doesn't reconcile.
- **Storage** — a `payslips` table (+ line-item deductions), git-ignored sample data like receipts (payslips
  are highly personal).

## Analytics (over time)

- Per-year **tax** and **social-insurance** paid; effective rate.
- **Month-over-month deltas** in gross/net/deductions, with the driver of a change surfaced (a raise, a
  one-off deduction, a rate change).
- Feeds the same drill-down model — every figure traces back to a payslip.

## Evaluation

Same as receipts ([D26](../../DECISIONS.md)): a small **git-ignored labelled payslip set** + the harness
scoring each field (gross/net/tax/insurance) against hand-verified truth, plus the gate's guardrail metrics.
Reuse `eval_models.py` for a model comparison on this new document type. Privacy handled exactly as the
receipt set is.

## Out of scope (initially)

Tax-return generation · multi-country payroll rules · employer/HR integrations · anything beyond reading and
tracking the user's own payslips.
