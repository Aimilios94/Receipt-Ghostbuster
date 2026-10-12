# Roadmap

*Phases and the goal for each. Updated at the completion of every phase. Status is the single source of truth for "what's built."*

The project ships in **deliberate phases** — each phase is a working, demoable product before the next begins. Shipping a polished small thing beats a half-built big thing, and the phased ship is itself the point: launch, get feedback, improve, repeat.

Legend: ✅ shipped · 🚧 in progress · ⬜ planned

---

## v0.1 — Track & Reconcile (MVP) ✅

**Goal:** turn any expense — snapped receipt or hand-typed cash — into one clean, reconciled, VAT-split ledger, and produce a real personal month-end.

**This is the MVP.** It is the smallest version that delivers the core promise end-to-end and is worth demoing on its own.

Scope delivered:
- Add expense two ways: **receipt snap** (vision-LLM extraction) and **manual / cash** entry.
- **Confidence gate** — uncertain extractions go to a review queue; confident ones auto-post.
- **Deterministic guardrails** on extraction (don't trust model confidence alone).
- Rules-based **categorization**; **VAT** split computed in code.
- **Bank CSV import** → **reconciliation** (amount + date window + fuzzy vendor), with cash excluded by design.
- **Exceptions**: unmatched, duplicate, amount-differs, missing-VAT (month-scoped).
- **Monthly close**: money in/out/net, VAT owed, unreconciled count — gated while card items are unreconciled.
- React + Vite frontend: Dashboard, Review queue, Reconciliation, Monthly close, Ledger.
- Backend test suite covering the accounting-critical paths.

Status: **shipped.**

---

## v0.2 — Refund Hunter ✅

**Goal:** find money leaking through forgotten recurring charges and make it one click to act on them — safely.

Scope delivered:
- **Subscription detection** across bank + ledger (vendor + amount grouping, cadence inference, annual cost, stale flagging).
- **Refund Hunter** screen: flag unused / keep / cancel / undo, with a savings summary.
- **Draft cancel/refund emails** (LLM with deterministic template fallback) — **draft-only, never auto-sent.**
- **n8n → Gmail** delivery: an approved draft becomes a real Gmail draft (orchestration/delivery only; all logic stays in FastAPI).

Status: **shipped.**

---

## v0.3 — Advice ⬜

**Goal:** move from recording the past to guiding the next decision — lightweight, rule-based, not a heavy AI advisor.

Planned scope:
- **Budget vs actual**: per-category budgets → variance view (`categories.budget_amount` already exists in the schema).
- **Overspend nudges** (`GET /insights`): rule-based signals (category over budget; spend up N% vs last month; paid-but-unused subscription) written to a new `insights` table.
- **Insights feed** on the dashboard.

Status: **planned** — not started.

---

## Planned improvements (from testing feedback)

- **Per-line VAT.** Today each expense stores a single VAT rate, so a mixed-rate receipt (e.g. 13% + 23%) is flattened to its dominant rate. Add a line-item table so a receipt can hold multiple rate lines and VAT is summed per rate in code — real accounting rigor. *(Decided to build later — 2026-10-12.)*
- **Duplicate detection at upload.** Flag likely duplicates when a receipt is uploaded, with a human double-check before posting (not only in reconciliation).
- **LLM-assisted categorization** for vendors the rules miss (e.g. Continente → Groceries).

## Beyond v0.3 (future work)

Not committed, but the natural directions: a mobile app, support for **more banks** (more CSV formats / open-banking), and **more languages / locales** for receipts and VAT rules. See the README's *Future work* section.
