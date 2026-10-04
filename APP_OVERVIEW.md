# Receipt Ghostbuster — App Overview

## What it is
A personal money assistant. Every expense — a snapped receipt or a hand-typed cash
entry — gets extracted, categorized, VAT-split, reconciled against the bank, and rolled
into a monthly summary. It then hunts dead subscriptions and advises where to cut.

**One line:** messy expense in → clean, reconciled, categorized record out — with a human
confirm gate and the weird stuff flagged.

## The problem it solves
People don't actually know where their money goes. Receipts get lost, cash spend is
invisible, subscriptions quietly renew, and no one runs a real month-end on their own
life. This app automates that, end-to-end.

## Who it's for
A single user managing their own money. Not multi-user, not for clients.

## Core concepts
- **Two ways to add an expense:** snap a receipt, or manual/cash entry with a note.
- **Every expense has a SOURCE:** card/bank (reconciled against statement) or cash
  (counted in totals, excluded from reconciliation — nothing in the bank to match).
- **Confidence gate:** high-confidence extractions auto-post; low-confidence go to a
  review queue. Nothing financial is trusted blindly to the AI.
- **One clean ledger** is the single source of truth the dashboard and reports read from.

## Phase 1 — Track & Reconcile (the shippable demo)
Add via receipt snap or cash/manual entry → extract vendor/amount/date/VAT →
auto-categorize → confidence gate → reconcile card/bank items against uploaded bank CSV
→ exceptions queue (unmatched, duplicate, amount-mismatch, missing VAT) → dashboard
(spend by category, VAT paid, cash vs card, cash-flow) → monthly close summary.

## Phase 2 — Refund Hunter
Detect recurring charges → flag unused/forgotten subscriptions → draft cancel/refund
emails for approval (draft-only, never auto-send) → track money saved.

## Phase 3 — Advice
Overspend nudges → flag unnecessary expenses → budget vs actual (variance) → surface
paid-but-unused subscriptions.

## Accounting depth
VAT breakdown · reconciliation exceptions report · cash-vs-bank source logic ·
automated monthly close · budget-vs-actual variance.

## Tech stack
React + Vite (frontend) · Python/FastAPI (extraction & reconciliation logic) ·
n8n (orchestration, refund emails) · Supabase (Postgres + auth + storage) ·
vision LLM for receipt extraction · bank data via CSV import.

## Out of scope
Multi-currency/FX · full double-entry bookkeeping · tax-return generation · multi-user ·
live open-banking API.
