# Receipt Ghostbuster 👻🧾

[![CI](https://github.com/Aimilios94/Receipt-Ghostbuster/actions/workflows/ci.yml/badge.svg)](https://github.com/Aimilios94/Receipt-Ghostbuster/actions/workflows/ci.yml)
[![extraction accuracy](https://img.shields.io/badge/extraction_accuracy-99.3%25-brightgreen)](backend/eval/RESULTS.md)
[![chatbot tool-selection](https://img.shields.io/badge/chatbot_tool--selection-100%25-brightgreen)](backend/eval/chatbot/RESULTS.md)
[![chatbot faithfulness judge](https://img.shields.io/badge/faithfulness_judge-calibrated-brightgreen)](backend/eval/chatbot/CALIBRATION.md)

**A personal money assistant that turns messy expenses into a clean, reconciled, VAT-split ledger — snap a receipt or type a cash expense, and it extracts, categorizes, reconciles against your bank, hunts dead subscriptions, and runs your month-end.**

> *messy expense in → clean, reconciled, categorized record out — with a human confirm gate and the weird stuff flagged.*

<!-- HERO GIF SLOT (Part 3): embed docs/screenshots/core-flow.gif here — snap → review → reconcile → close -->
![Dashboard](docs/screenshots/dashboard.png)

*Live demo: runs locally — see [Run it yourself](#run-it-yourself). A hosted demo link is planned.*

---

## The problem

People don't actually know where their money goes: receipts get lost, cash spend is invisible, subscriptions renew silently, and nobody runs a real month-end on their own life. Receipt Ghostbuster automates that whole manual process end-to-end, for a single person managing their own money (VAT included).
→ Full write-up: **[problem-statement.md](problem-statement.md)**.

---

## Features by version

See the full plan and status in **[roadmap.md](roadmap.md)**.

- **v0.1 — Track & Reconcile (MVP) ✅ shipped**
  Receipt snap + cash/manual entry → vision-LLM extraction → confidence gate + deterministic guardrails → rules categorization + VAT (computed in code) → bank CSV import → reconciliation → month-scoped exceptions → monthly close. Screens: Dashboard, Review queue, Reconciliation, Monthly close, Ledger.
- **v0.2 — Refund Hunter ✅ shipped**
  Detects recurring charges, flags unused ones, drafts cancel/refund emails (draft-only), and delivers them as real **Gmail drafts** via n8n. Plus: clickable dashboard drill-downs, per-rate VAT breakdown, duplicate surfacing, and a richer review/edit flow.
- **v0.2.2 — Per-line VAT & testing fixes ✅ shipped**
  **Per-line VAT** (a receipt can hold multiple rates — summed per rate in code, bucket-rounded to match the printed IVA summary), a **multi-rate VAT editor** in the review queue, **duplicate detection at upload**, clickable Ledger rows → full expense detail, editable rows, and clickable status. From the Round 2 testing session (see [feedback-notes.md](feedback-notes.md)).
- **v0.2.3 — Extraction robustness & review UX ✅ shipped**
  From a Round 3 session on hard real receipts (3-rate, discounted, no-VAT, sideways, crumpled): **LLM categorization**, the **printed IVA table as VAT source of truth**, **estimated VAT** when none is printed (clearly flagged), **discount handling**, **server-side auto-rotation** (Pillow), **date year-repair**, a **self-consistency guardrail** + **retake** flow, editable Ledger category, and clickable/deletable reconciliation exceptions. Backend tests **53 → 80** (see [feedback-notes.md](feedback-notes.md), [D14–D21](DECISIONS.md)).
- **v0.2.4 — Bank statements & reconciliation workbench ✅ shipped**
  From a Round 4 session on a real **Revolut** export: **PDF + Revolut-aware CSV import** (auto-detected columns, skips pending/reverted rows), a **Bank statements** section (each file's period + Spent/Received/Net, drill-down), top-ups/transfers excluded from the receipt cycle, and a hand-drivable **reconciliation workbench** — match / unmatch / not-a-match / **No receipt** for online payments / **Match manually**, with believable suggestions only and **View transaction** (the exact CSV row). Plus **replace-a-receipt-photo** (re-scan) and a printed-VAT consistency fix. Backend tests **80 → 97** (see [feedback-notes.md](feedback-notes.md), [D22–D25](DECISIONS.md)).
- **v0.2.5 — Measured accuracy & a reading upgrade ✅ shipped**
  Built a field-level **extraction-accuracy eval harness**, which showed `gpt-4o` mis-reads dense multi-rate VAT tables — so receipt reading moved to the **`gpt-5-mini` reasoning model** (**84% → 93%**). Plus read-every-orientation rotation handling, a retake prompt that trusts reconciliation over self-reported confidence, an Uber-Eats→Dining fix, and a **"No bank line"** action so the reconciliation Unmatched list can reach a clean state. Backend tests **97 → 99** (see [feedback-notes.md](feedback-notes.md), [D26–D28](DECISIONS.md)).
- **v0.2.6 — Robust duplicate detection & a self-contained receipt viewer ✅ shipped**
  From a Round 6 session on two look-alike real receipts: **duplicate detection now matches on vendor + total within a ±30-day window** (brand-prefix vendor match), not on an exact date — so a re-upload is caught even when the model reads the date or vendor slightly differently. Plus a shared receipt lightbox where **Esc / ✕ / backdrop close only the image**, not the dialog behind it. Backend tests **99 → 109** (see [feedback-notes.md](feedback-notes.md), [D29](DECISIONS.md)).
- **v0.3.0 — LLM Observability & Evaluation ✅ shipped**
  Validated structured outputs (**Instructor** + Pydantic, with a safe fallback), per-call **tracing** (latency / tokens / estimated cost / gate outcome) in a new `llm_traces` table, a **measured guardrail** story (the gate is factored into one function the eval also runs — reporting false-auto-post rate, over-review rate and confidence calibration), and an in-app **Model & Evals** dashboard. Optional **LangSmith** tracing + experiments, opt-in. Structured outputs lifted eval accuracy **93% → 98%**. Backend tests **109 → 128** (see [D30](DECISIONS.md)).
- **v0.3.4 — Regression gate & error tracking ✅ shipped**
  An **accuracy-regression gate** (`check_regression.py` vs a committed baseline — local on the real cached number, CI on a deterministic mock mechanism) with **CI + accuracy badges**, a guardrail-matrix + schema-coercion test expansion, and **opt-in Sentry error tracking** (app-layer complement to LangSmith + the eval) with a privacy scrubber so no receipt/bank data leaves the machine, plus a free **Sentry-MCP AI-debug loop**. It immediately earned its keep: a real error (an undecodable upload 500ing as "can't reach the backend") was **caught in Sentry, root-caused and fixed** — see the [worked example](docs/MONITORING.md#worked-example-a-real-error-caught-and-fixed). Backend tests **137 → 207** (see [D34](DECISIONS.md), [docs/MONITORING.md](docs/MONITORING.md)).
- **v0.4 — Advice ✅ shipped**
  Moves from recording the past to guiding the next decision — **deliberately rule-based and LLM-free** (extends "the AI never does the math" to guidance, [D36](DECISIONS.md)). Per-category **budgets** with a **budget-vs-actual** view, three deterministic nudges (**over budget**, **spending up ≥25% vs last month**, **paid-but-unused subscription**), a persisted/dismissable **insights feed** on both the Dashboard and a dedicated **Advice** page, and **actionable** nudges (deep-link to draft a cancellation, view the category's ledger, or adjust the budget). From the same Round 8 session: **Refund Hunter detection hardened** (top-ups/transfers and one-off retail excluded; a subscription now needs **≥3** same-amount charges, not a coincidence of 2; stale auto-detections pruned), each subscription shows its **charge dates** and a **"view charges"** snapshot (the exact bank/CSV rows), and a cross-cutting **modal-centering fix**. Backend tests **207 → 227** (see [feedback-notes.md](feedback-notes.md), [D36–D37](DECISIONS.md)).
- **v0.4.2 — Idempotent bank re-upload & spending breakdown ✅ shipped**
  From a Round 9 session re-importing a fuller **Revolut** export: **bank-statement re-upload is now idempotent** — a count-aware fingerprint (date + amount + description + running balance) inserts only genuinely-new rows and preserves reconciliation, so an overlapping re-upload no longer duplicates the overlap ([D38](DECISIONS.md)). Plus a deterministic **Spending breakdown** (expenses by vendor, and bank transfers grouped by counterparty split **sent/received**, with the user's **own-Revolut movements** in their own section), each row drilling to its transactions, reachable from Reconciliation and the Ledger ([D39](DECISIONS.md)). Backend tests **227 → 241** (see [feedback-notes.md](feedback-notes.md), [D38–D39](DECISIONS.md)).
- **v0.5 — Ask chatbot (NL Q&A) ✅ shipped**
  Ask your money questions in plain language — *"which day did I spend the most?", "what do I buy most at Pingo Doce?", "send me the CSV for 1–18 Oct", "which of my payments might be a subscription?"* — over the same one ledger. Built as **tool-calling over a fixed, pure, unit-tested analytics surface** (`services/analytics.py`): the model only interprets the question and **selects** the right calculation; **every number is computed in code**, never by the model (extends "the AI never does the math" to Q&A, [D40](DECISIONS.md)). Natural, direct answers with rich inline results (receipt images, a transactions table + Download CSV, an expandable grouped-by-vendor list), and honest subscription reasoning (cash + one-off consumption are never subscriptions). **It ships with its own measured quality story** — shipped in three slices:
  - **Slice 1 — the chatbot** ([D40](DECISIONS.md)).
  - **Slice 2 — a built-in eval harness** ([D41](DECISIONS.md)) over a **committed, synthetic** fixed ledger (reproducible + public-safe, unlike the git-ignored real receipts): **tool-selection accuracy** (the LLM's real job — right tool, right args), **answer-correctness** (the figure, graded in code — no LLM judge), and **refusal** (out-of-scope questions must decline). On gpt-5-mini: **tool-selection 18/18, answer 18/18, refusal 5/5**; the offline check is deterministic and gated in CI.
  - **Slice 3 — a calibrated faithfulness judge + a response cache** ([D42](DECISIONS.md)). An LLM judge checks the **prose** follows from the computed numbers; it's **calibrated against human-verified labels before it's trusted** (100% agreement, caught 100% of unfaithful answers → **TRUSTED**; live prose **18/18 faithful**). Plus an in-process response cache keyed on a **ledger fingerprint** that self-invalidates on any data change. Backend tests **241 → 287** (see [docs/design/chatbot.md](docs/design/chatbot.md), [D40–D42](DECISIONS.md)).

---

## What makes it more than a CRUD app

| Principle | How it shows up | Why |
|---|---|---|
| **The AI is never trusted blindly** | Vision extraction gets a confidence score; a **code-level guardrail** (`validation.py`) runs regardless. Confident + clean → auto-post; anything uncertain → review queue. **All VAT/reconciliation/close math is computed in code.** | [D1](DECISIONS.md#d1--the-ai-is-never-trusted-blindly-design), [D6](DECISIONS.md) |
| **Cash vs bank is first-class** | Cash counts in totals but is *excluded from reconciliation* — so it never shows as a false "unmatched" exception. | [D3](DECISIONS.md) |
| **One ledger is the source of truth** | Every dashboard number drills down to the exact expenses behind it (with receipt view). Nothing double-entered. | [D10](DECISIONS.md) |
| **Nothing financial auto-sends** | Cancellation emails are **draft-only** — n8n creates a Gmail draft, you send it. | [D4](DECISIONS.md) |
| **Fails safe on bad input** | A sideways photo is **auto-rotated** server-side; a crumpled/unreliable read (incl. a VAT table that disagrees with its own item lines) is routed to review with reasons and a **retake** option, not silently mis-posted. | [D9](DECISIONS.md), [D20](DECISIONS.md), [D21](DECISIONS.md) |
| **Reads, never guesses** | The printed IVA summary table is the VAT source of truth; discounts are modelled, not treated as products; VAT it can't read is clearly marked an **estimate** for you to confirm. | [D14](DECISIONS.md), [D17](DECISIONS.md), [D18](DECISIONS.md) |
| **Your data stays yours** | A **local-model option** (Ollama) reads receipts fully **on-device** — nothing leaves the machine; bank-statement text has **IBAN / card numbers redacted** before any cloud call; the LangSmith tracer is opt-in. The privacy↔accuracy cost of going local is **measured**, not assumed. | [PRIVACY.md](docs/PRIVACY.md) |
| **Ask it anything — but the AI never does the math** | The **Ask** chatbot answers plain-language questions by **tool-calling** a fixed, unit-tested analytics surface; it picks the calculation, **the code computes every number**. It ships *measured*: tool-selection accuracy, answers graded in code, refusals, and prose faithfulness checked by a **calibrated** judge. | [D40](DECISIONS.md), [D41](DECISIONS.md), [D42](DECISIONS.md) |

---

## How it works

```
Browser (React + Vite, :5173)
        │  JSON over HTTP  (talks ONLY to the backend)
        ▼
FastAPI backend (:8000)        ← vision LLM for receipt extraction (server-side key)
  extraction · confidence gate + guardrails · categorization
  VAT math · reconciliation · exceptions · monthly close · subscription detection
  Ask chatbot → tool-calling over a fixed analytics surface (every number computed in code)
        │                                    │
        ▼                                    ▼
Supabase (Postgres + Auth + Storage)   n8n (Docker, :5678) → Gmail draft (draft-only)
```

**Stack & why:**
- **React + Vite** — fast SPA for a dashboard-heavy UI.
- **Python / FastAPI** — all logic as tested endpoints (the accounting-critical paths are unit-tested).
- **Supabase (Postgres + Auth + Storage)** — managed DB, row-level security, and receipt image storage without standing up infra.
- **Vision LLM (OpenAI `gpt-5-mini`)** — reads receipts *and* powers the Ask chatbot's tool-calling; provider is swappable (Anthropic / a local on-device Ollama model), and the choice was made with an eval (see Results — `gpt-4o` is the compared baseline).
- **n8n** — thin orchestration for Gmail delivery + cron, so email logic stays out of the app ([D5](DECISIONS.md)).
- **Bank via CSV import** — works with any bank, no open-banking OAuth ([D2](DECISIONS.md)).

---

## Results

- **Extraction accuracy (measured):** a reproducible harness ([`backend/scripts/eval_extraction.py`](backend/scripts/eval_extraction.py)) scores the shipped pipeline — the vision read **plus** the deterministic VAT/amount/category logic — field-by-field against a hand-labelled set of 26 real Portuguese receipts (multi-rate VAT tables, rotated photos, discounts, a crumpled receipt, a 0%-VAT tobacco receipt, a payment-only receipt, and a handwritten prompt-injection receipt). On `gpt-5-mini`:

  | vendor | date | total | vat amount | vat rate | category | **overall** |
  |---:|---:|---:|---:|---:|---:|---:|
  | 100% | 96% | 100% | 100% | 100% | 100% | **99.3%** |

  Choosing the model was itself eval-driven: `gpt-4o` scored **84%** and reliably mis-read dense 3-rate VAT tables; swapping in the `gpt-5-mini` reasoning model (which reads those tables correctly) lifted it to **93%**, and validated structured outputs (Instructor, v0.3.0) took it to **98%** — and on the grown 26-receipt set it holds at **99.3%**, the one miss a date read a day off. (The eval also caught a *labelling* error of its own — a tobacco receipt labelled 0%/Tobacco from outside knowledge the receipt doesn't print; corrected, because an extraction label must score only what's on the paper.) See [`backend/eval/RESULTS.md`](backend/eval/RESULTS.md).
- **Model comparison (accuracy × latency × cost × privacy):** a reproducible runner ([`backend/scripts/eval_models.py`](backend/scripts/eval_models.py)) scores several models over the same set on every axis a production choice turns on, and breaks accuracy down **by receipt type** so a strong average can't hide a weak slice. Run over 26 receipts — **gpt-5-mini 98.6%** · **gpt-4o 92.3%** · **claude-haiku-4-5 86.6%** · **claude-opus-4-8 98.2%** (frozen at n=20) · and a **local, on-device `qwen2.5vl:7b` at 89.4%**. Two decisive findings: **Opus ties gpt-5-mini on accuracy but costs ~39× more per read** ($0.32 vs $0.0076), so the cheap reasoning model wins on accuracy *and* cost; and a **free local model (data never leaves the machine) reaches ~90%** — above cloud Haiku — the privacy↔accuracy price quantified (the catch is latency: ~5–18 min/read on CPU). See [`backend/eval/MODELS.md`](backend/eval/MODELS.md) and [D33](DECISIONS.md). Each cloud model's run is also pushed to **LangSmith** as an Experiment; the local reads deliberately are not (privacy). *(n=26, so small differences aren't significant.)*

  ![LangSmith model comparison](docs/screenshots/Langsmith-compare-experiments.png)
  *The same runs in **LangSmith** — three experiments (gpt-5-mini / gpt-4o / Haiku) compared against the receipt dataset: per-field feedback scores, latency (p50/p99), token count and estimated cost side by side, over a per-receipt pass/fail grid. Opt-in; the offline eval depends on none of it.*
- **Guardrails, measured (not asserted):** the same harness runs the shipped review gate over the set and reports whether it actually catches bad reads — the **false-auto-post rate**, the **over-review rate**, and a **confidence-calibration** table — surfaced in an in-app **Model & Evals** dashboard alongside live per-read latency/cost. An honest finding it produced: the model's self-reported confidence is poorly calibrated (0.7–0.8 reads were 100% correct, 0.8–0.9 only 75%), so the gate currently over-reviews correct reads. See [D30](DECISIONS.md).

![Model & Evals dashboard](docs/screenshots/model-evals.png)
*The in-app **Model & Evals** page: field accuracy, guardrail effectiveness, confidence calibration, and live per-read latency/cost/outcome — the layers a production LLM feature has and a demo usually skips.*
- **Ask chatbot (measured):** the NL Q&A chatbot ships with its own eval harness ([`backend/scripts/eval_chatbot.py`](backend/scripts/eval_chatbot.py)) over a **committed, synthetic** fixed ledger — reproducible and public-safe, unlike the git-ignored real receipts. On `gpt-5-mini`: **tool-selection 18/18** (did it call the right analytics tool with the right args — the LLM's actual job), **answer-correctness 18/18** (the figure, graded in **code** by dispatching the tool — no LLM judge), **refusal 5/5** (out-of-scope questions declined). Prose faithfulness is checked by a **calibrated** LLM judge — measured against human-verified labels before it's trusted: **100% agreement, 100% recall on catching unfaithful answers → TRUSTED**, and live answers score **18/18 faithful**. The offline answer-check is deterministic and gated in CI; the model-dependent numbers run locally (like the extraction eval). See [`backend/eval/chatbot/RESULTS.md`](backend/eval/chatbot/RESULTS.md) and [`CALIBRATION.md`](backend/eval/chatbot/CALIBRATION.md).
- **Reconciliation / close:** figures reconcile to the cent against the ledger (covered by pytest). Bank import handles a real Revolut CSV and text-based PDF statements; reconciliation can be driven by hand (match / unmatch / not-a-match / no-receipt) with believable suggestions only.
- **Tests:** **287 passing** — reconciliation + manual-match + no-bank-match helpers, VAT incl. per-line/mixed-rate + bucket rounding + printed-table source of truth, categorization incl. food-delivery rules, date re-read + year-repair, discounts, estimated/0% VAT, duplicate fingerprinting, idempotent statement de-dup, spending breakdown, the gate decision + guardrail/calibration metrics, LLM-trace cost/usage helpers, the local Ollama provider wiring, IBAN/card redaction, close, exceptions, validation, subscriptions, CSV/PDF bank import, statement aggregation, **the chatbot analytics + tool dispatch, the chatbot eval scoring + judge-agreement, the faithfulness judge, and the response cache**.
- **Impact:** turns a manual personal month-end into minutes; surfaces forgotten subscriptions by annual cost.

---

## Process (how this was built)

This project is built the way a product engineer works — ship small, test, capture feedback, decide, iterate:

- **[roadmap.md](roadmap.md)** — phases, goals, and what's planned.
- **[DECISIONS.md](DECISIONS.md)** — every real decision as Problem → Evidence → Decision → Result.
- **[feedback-notes.md](feedback-notes.md)** — real testing rounds; the evidence behind the decisions.
- **[CHANGELOG.md](CHANGELOG.md)** — what changed per version.

---

## Run it yourself

### Prerequisites
- **Python 3.14** and **Node 18+**
- A **Supabase** project and a **vision-LLM API key** (OpenAI or Anthropic)
- Copy `backend/.env.example` → `backend/.env` and fill it in. Set `DEV_USER_ID` to a user UUID for keyless demo mode. Copy `frontend/.env.example` → `frontend/.env` (defaults to `VITE_API_BASE_URL=http://localhost:8000`).

```powershell
# backend
cd backend
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\apply_schema.py
.\.venv\Scripts\python.exe scripts\load_sample_data.py   # expenses + bank CSV + reconcile

# frontend
cd ..\frontend
npm install
```

### Start it
```powershell
# Terminal 1 — backend (API on :8000). On Windows run ONE process, no --reload.
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# Terminal 2 — frontend (UI on :5173)
cd frontend
npm run dev
```
Open **http://localhost:5173**. API docs at **http://localhost:8000/docs**.
Refund Hunter's Gmail delivery (Phase 2) needs n8n — see **[n8n/README.md](n8n/README.md)**.

### Tests
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

---

## Demo script (≈3 minutes)

The sample dataset is shaped so **every reconciliation path shows up**:

1. **Dashboard** — opens on the latest month with data. Click any number (Total spent, VAT, Card/cash, Reconciled, a category) to drill into the exact expenses behind it. *"Every number is computed in code and traces back to the ledger."*
2. **Add → Snap a receipt** — a confident read auto-posts; a shaky/rotated one lands in the **Review queue** with reasons. *"The AI is never trusted blindly."*
3. **Add → Manual / cash** — add cash; it counts in totals but is **never** a reconciliation exception.
4. **Reconciliation** — **Run reconciliation**, then walk the exceptions (amount-differs, duplicate, no-bank-match). Hit **Resolve** on the duplicate → the Ledger filters to the flagged pair, badged side by side.
5. **Monthly close** — money in/out, VAT owed, and a close gated while card items are unreconciled.
6. **Refund Hunter** — detected subscriptions by annual cost; draft a cancellation email → **Save to Gmail drafts** (draft-only).
7. **Advice** — budget-vs-actual + rule-based nudges (over budget / spending up / unused subscription), each deep-linking to the fix. *"Deterministic guidance — the AI stays out of the math here too."*
8. **Ask** — type a plain-language question (*"which day did I spend the most in October?"*, *"show me the receipt for Pingo Doce"*). The answer is phrased by the model but **every number comes from a tool computed in code**; receipts and CSVs render inline; out-of-scope questions are declined.
9. **Model & Evals** — the in-app view of extraction accuracy, guardrail effectiveness and live per-read latency/cost — the measured-quality story, in the product.

---

## Out of scope

Multi-currency / FX · full double-entry bookkeeping · tax-return generation · multi-user / client accounts · live open-banking API.

## Future work

A hosted live demo · a mobile app · support for more banks (more CSV formats / open-banking) · more languages/locales for receipts and VAT rules · **payslip tracking** (bring income in — gross/net, tax and social-insurance deductions over time, v0.6, designed in [docs/design/payslip.md](docs/design/payslip.md)). See [roadmap.md](roadmap.md).
