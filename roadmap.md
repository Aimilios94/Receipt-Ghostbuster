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

## v0.2.4 — Bank statements & reconciliation workbench ✅

**Goal:** make bank import work with a real-world export and turn reconciliation from a one-shot auto-pass into a view the user can drive and trust.

Scope delivered:
- **PDF bank-statement import** alongside CSV (text-extracted + LLM-structured, with a deterministic fallback); scanned PDFs rejected clearly ([D22](DECISIONS.md)).
- **Robust CSV import** — auto-detects column names (incl. Revolut `Completed Date`, debit/credit) across EN/PT/ES/DE, sniffs the delimiter, strips time components, skips not-yet-settled rows; never stores a blank date.
- **Top-ups / transfers aren't purchases** — excluded from the "needs a receipt" cycle ([D23](DECISIONS.md)).
- **Bank statements section** — each imported file as a first-class entity (period, Spent/Received/Net, drill into transactions); unmatched bank lines collapse into one row per statement ([D24](DECISIONS.md)).
- **Reconciliation workbench** — a results popup with match / unmatch / not-a-match, believable suggestions only, **No receipt** for online payments, **Match manually** on demand, and **View transaction** (the exact CSV row) ([D25](DECISIONS.md)).
- **Replace-a-receipt-photo (re-scan)** from anywhere a receipt is shown — uploads a new photo, replaces the image, and re-reads it.
- **Fixes:** printed IVA table accepted within a relative tolerance and scaled to the exact total (consistent net/VAT/paid, extends [D14](DECISIONS.md)); per-thread Supabase client (no transient Windows socket errors under concurrent load).

Status: **shipped.** Backend tests **80 → 97**.

---

## v0.2.5 — Measured accuracy & a reading upgrade ✅

**Goal:** stop guessing at extraction quality — measure it, then fix what the numbers expose, and let reconciliation reach a clean state.

Scope delivered:
- **Extraction-accuracy eval harness** — `scripts/eval_extraction.py` scores the shipped pipeline field-by-field over a hand-labelled receipt set; aggregate table in `backend/eval/RESULTS.md` ([D26](DECISIONS.md)).
- **Model upgrade to gpt-5-mini** — a reasoning model that reads dense multi-rate VAT tables correctly (gpt-4o mis-read them); **eval 84% → 93%** ([D27](DECISIONS.md)).
- **Reads every orientation** (incl. 180°) and keeps the most complete read, instead of stopping at the first plausible one ([D27](DECISIONS.md)).
- **Retake prompt trusts reconciliation over self-reported confidence** — no more "retake" nag on a read that reconciles to the cent ([D27](DECISIONS.md)).
- **Uber Eats → Dining** categorization fix (was Transport).
- **"No bank line"** — the expense-side mirror of "No receipt"; clears an unmatched expense out of the reconciliation cycle so the Unmatched list can reach a clean state ([D28](DECISIONS.md)).

Status: **shipped.** Backend tests **97 → 99**.

---

## v0.2.6 — Robust duplicate detection & a self-contained receipt viewer ✅

**Goal:** make the upload-time duplicate check survive the model's own misreads, and stop receipt viewing from throwing the user out of the dialog they were working in.

Scope delivered:
- **Duplicate fingerprint = vendor + total, within a ±30-day window** — no longer an exact-date match. Vendor is matched by *brand prefix* (`Pingo Doce` ≡ `Pingo Doce - PD Olaias`), so a re-upload is caught even when the date or vendor reads differently; still routed to review, never auto-posted ([D29](DECISIONS.md)).
- **Shared `ReceiptLightbox`** — Esc, a ✕ button, and a backdrop click close only the image, leaving the dialog behind it open; rolled out to all six receipt viewers.

Status: **shipped.** Backend tests **99 → 109**.

---

## v0.3.0 — LLM Observability & Evaluation ✅

**Goal:** turn the extraction from "a model call that seems to work" into a system you can measure, observe and trust — the layers a production LLM feature has and a demo usually skips.

Scope delivered ([D30](DECISIONS.md)):
- **Validated structured outputs (Instructor)** — the model's JSON is validated against `ExtractionResult` with automatic re-prompting, and a tolerant raw-parse fallback. Prompt unchanged; measured eval accuracy **93% → 98%**.
- **Per-call tracing** — latency, tokens, estimated cost and the gate outcome recorded to an `llm_traces` table for every read (the SDK usage used to be discarded).
- **Measured guardrails** — the gate was factored into one pure `decide_gate` used by both `/extract` and the eval, so the eval reports the **false-auto-post rate**, **over-review rate** and **confidence calibration** of the shipped gate.
- **Model & Evals dashboard** (`/model-evals`) — accuracy by field, guardrail effectiveness, calibration, and live latency/cost/outcome per read.
- **Optional LangSmith** — opt-in tracing + a dataset/experiment script; off by default, no hard dependency.

Honest finding the eval surfaced: the self-reported confidence is poorly calibrated (0.7–0.8 reads were 100% correct, 0.8–0.9 only 75%), so the gate over-reviews correct reads — quantifying the deferred "auto-post on reconcile" question with data.

Status: **shipped.** Backend tests **109 → 128**.

---

## v0.3.2 — Evaluation, next level ✅

**Goal:** go beyond a single accuracy number — compare models on the axes that actually decide a
production LLM choice (accuracy, latency, cost) and expose where accuracy is weak, not just the average.

Scope:
- **Multi-model comparison** — `scripts/eval_models.py` runs the shipped pipeline across models
  (gpt-5-mini incumbent, gpt-4o, Claude Haiku 4.5) and writes an **accuracy × latency × cost** matrix to
  `backend/eval/MODELS.md` / `models.json`. A fairness fix (Anthropic output-token ceiling) makes Claude's
  reads of dense multi-rate VAT tables comparable. The single-model `RESULTS.md`/`metrics.json` the in-app
  page reads stays the canonical shipped number.
- **Accuracy by receipt type** — optional `tags` on labels (rotated / multi-rate / discount / payment-only
  …) so the harness breaks accuracy down by slice; a strong average can't hide a weak case.
- **LangSmith per-model experiments** — `scripts/langsmith_eval.py` takes `--provider/--model`, so each
  model is its own Experiment for the LangSmith compare view (opt-in, unchanged otherwise).
- **Honesty:** the comparison states n=11 and that small differences aren't statistically significant.

Run over 20 receipts: **gpt-5-mini 98.2%** · **gpt-4o 94.5%** · **claude-haiku-4-5 87.3%** — the spread is
mostly VAT, and gpt-5-mini is the slowest but the cheapest per read *and* most accurate
([D31](DECISIONS.md), `backend/eval/MODELS.md`). Growing the set 11→20 surfaced rotation as the weak slice
(and caught a mislabelled receipt — corrected). The Opus 4.8 column is pending its Anthropic credits.

Deferred to a later eval round: structured-output reliability taxonomy, an accuracy-regression CI gate,
and a calibrated LLM-as-judge.

Status: **shipped.** Backend tests **128 → 130**.

---

## v0.4 — Advice ⬜

**Goal:** move from recording the past to guiding the next decision — lightweight, rule-based, not a heavy AI advisor.

Planned scope:
- **Budget vs actual**: per-category budgets → variance view (`categories.budget_amount` already exists in the schema).
- **Overspend nudges** (`GET /insights`): rule-based signals (category over budget; spend up N% vs last month; paid-but-unused subscription) written to a new `insights` table.
- **Insights feed** on the dashboard.

Status: **planned** — not started.

---

## v0.5 — Refund Hunter chatbot (NL Q&A) ⬜

**Goal:** let the user *ask* their money questions in plain language — "which day did I spend the most this
month?", "which week do I usually spend least?", "how much went to Groceries vs last month?" — on top of the
same one ledger, not just read dashboards.

Planned scope (design: [docs/design/chatbot.md](docs/design/chatbot.md)):
- **Tool-calling architecture** — the LLM selects and sequences **analytics functions that compute every
  number in code** (extending [D1](DECISIONS.md) "the AI never does math" to Q&A); it never free-form sums or
  invents figures.
- **Grounded answers only** — responses cite the computed result; a question outside the data is declined.
- **Evaluation built-in** — deterministic questions have a **computable exact ground truth** (so they're
  scored without a judge); open-ended answers get a **calibrated LLM-as-judge** for faithfulness.

Status: **planned** — not started.

---

## v0.6 — Payslip tracking ⬜

**Goal:** bring income into the picture — upload a payslip and track gross/net, tax and social-insurance
deductions over time, so "where my money goes" includes "what's taken before it arrives."

Planned scope (design: [docs/design/payslip.md](docs/design/payslip.md)):
- **Payslip extraction** — the same vision-read-then-compute-in-code pipeline as receipts, a new field set
  (gross, net, income tax, social insurance, other deductions), its own git-ignored labelled eval set.
- **Over-time analytics** — per-year insurance/tax paid, month-over-month deltas and the reason for a change.

Status: **planned** — not started.

---

## Planned improvements (from testing feedback)

- **Per-line VAT.** ✅ Built — an `expense_line_items` table holds one VAT rate per line, so a mixed-rate receipt (e.g. 6% + 23%) is summed per rate in code instead of flattened to its dominant rate (see [D12](DECISIONS.md#d12--per-line-vat-a-receipt-can-hold-multiple-rates-design)). Mechanism verified end-to-end against live Supabase; a real gpt-4o read of a mixed-rate receipt photo is the remaining confirmation step.
- **Duplicate detection at upload.** ✅ Built — `/extract` checks for an existing row with the same vendor + amount + date and routes a match to the review queue with an in-app warning, before anything posts (see [D13](DECISIONS.md#d13--flag-duplicates-at-upload-before-they-post-r2)).
- **LLM-assisted categorization.** ✅ Built — rules first, gpt-4o fills unknown vendors (Continente/Pingo Doce → Groceries), validated against the category list; added a Tobacco category (see [D15](DECISIONS.md)).
- **Extraction robustness (Round 3).** ✅ Built — printed IVA table as VAT source of truth, discount handling, estimated VAT when none is printed, date year-repair + re-read, net-vs-gross correction, server-side auto-rotation, and a self-consistency guardrail + retake flow (see [D14–D21](DECISIONS.md)). Backend tests 53 → 80.
- **Bank statements & reconciliation workbench (Round 4).** ✅ Built — PDF import, Revolut-aware CSV import, statements as first-class entities, collapsed exceptions, and a hand-drivable reconciliation popup (match / unmatch / not-a-match / no-receipt / re-scan) with believable suggestions only (see [D22–D25](DECISIONS.md)). Backend tests 80 → 97.
- **Extraction-accuracy eval harness.** ✅ Built (v0.2.5) — a labelled receipt set + `scripts/eval_extraction.py` gives a real field-level accuracy number (93% on gpt-5-mini); see [D26](DECISIONS.md) and `backend/eval/RESULTS.md`. It drove the model upgrade in [D27](DECISIONS.md).
- **Read-twice-and-compare** consensus mode. ⬜ Deferred option for maximum reliability on the hardest (crumpled + rotated) receipts.
- **`claude-opus-4-8` eval comparison.** ⬜ Pending Anthropic credits — add a cross-model column to RESULTS.md.

## Beyond v0.3 (future work)

Not committed, but the natural directions: a mobile app, support for **more banks** (more CSV formats / open-banking), and **more languages / locales** for receipts and VAT rules. See the README's *Future work* section.
