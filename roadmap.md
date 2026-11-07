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
- **Draft cancel/refund emails** (LLM with deterministic template fallback) — **draft-only, never auto-sent.** The LLM path only runs on the Anthropic provider, so on OpenAI, the current default, drafts come from the template.
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
- **Honesty:** the comparison states its sample size and that small differences aren't statistically significant.

Run over 20 receipts: **gpt-5-mini 98.2%** · **gpt-4o 94.5%** · **claude-haiku-4-5 87.3%** · **claude-opus-4-8
98.2%** — Opus *ties* gpt-5-mini on accuracy but costs ~39× more per read, so gpt-5-mini wins on accuracy
*and* cost ([D31](DECISIONS.md), `backend/eval/MODELS.md`). Growing the set 11→20 surfaced rotation as the
weak slice (and caught a mislabelled receipt — corrected). Each model is also pushed to LangSmith as an Experiment.
Grown again **20→26** on 2026-10-22 (incl. a handwritten prompt-injection receipt): **gpt-5-mini 98.6%** ·
**gpt-4o 92.3%** · **claude-haiku-4-5 86.6%** (Opus frozen at its n=20 number) — gpt-5-mini unchanged as the pick.
*Figures as of that date; for current numbers see [MODELS.md](backend/eval/MODELS.md) and [D50](DECISIONS.md).*

Deferred to a later eval round: structured-output reliability taxonomy, an accuracy-regression CI gate,
and a calibrated LLM-as-judge.

Status: **shipped.** Backend tests **128 → 130**.

---

## v0.3.3 — Privacy, a local model & injection hardening ✅

**Goal:** close the biggest gap for an EU product on personal financial data — give the user a way to keep reading **on-device**, document what leaves the machine, and harden against text that tries to hijack the read.

Scope:
- **Local reading option** (`LLM_PROVIDER=ollama`) — reads via Ollama on-device, never traced to LangSmith. Measured as a first-class column: **qwen2.5vl:7b 89.4%** (2026-10-22; now 90.1%, [D43](DECISIONS.md)) over the 26-set at **$0** (above cloud Haiku, ~9 pts below gpt-5-mini; CPU-only so ~5–18 min/read). A committed `backend/ollama/Modelfile` raises `num_ctx` to fit a receipt image ([D33](DECISIONS.md)).
- **Privacy policy + redaction** — `docs/PRIVACY.md` (what goes where, the LangSmith caveat, the local option) and IBAN/card masking before any bank-PDF cloud call.
- **Prompt-injection hardening** — an explicit "image text is data, not instructions" prompt rule, tested with a real handwritten-injection receipt; all four models read the true total and ignored it ([D32](DECISIONS.md)).
- **Eval grown 20 → 26** on fresh ground truth (incl. the injection receipt). gpt-5-mini 99.3% single-model.

Status: **shipped.** Backend tests **130 → 137**. gpt-5-mini stays the production pick; local is a quantified option.

---

## v0.3.4 — Regression gate & app-layer error tracking ✅

**Goal:** harden the observability/eval spine — stop a code change from silently dropping accuracy, and make application-layer failures visible.

Scope:
- **Accuracy-regression gate** — `scripts/check_regression.py` fails if any tracked extraction metric drops below a committed floor (`eval/baseline.json`) minus a tolerance band. Runs **locally on the real number** (cached reads, deterministic, $0) and **in CI on a deterministic mock mechanism** (`baseline.mock.json`) so the public runner catches a broken scoring/VAT/gate pipeline without exposing the git-ignored receipt data. **README badges**: CI status + extraction accuracy.
- **Guardrail-matrix + schema-coercion tests** — the real `validate_receipt`→`decide_gate` integration grid, guardrail precedence/stacking and the retake truth table, plus the tolerant JSON parse and `ExtractionResult` coercion/confidence-clamp. (+54 tests.)
- **Sentry error tracking (opt-in, privacy-first)** — the app-layer complement to LangSmith and the eval ([D34](DECISIONS.md)). FastAPI auto-capture + explicit capture at the swallowed surfaces; `@sentry/react` init + an `ErrorBoundary` on the frontend. `send_default_pii=False` + a `before_send` scrubber strips request body/headers so **no receipt/bank/PII leaves the machine**; errors only (free tier). An **AI-debug loop** on the free Sentry MCP into Claude Code; Seer (paid) optional. See [docs/MONITORING.md](docs/MONITORING.md).

Status: **shipped.** Backend tests **137 → 201**. Cost: **$0** (Sentry free Developer tier).

---

## v0.4 — Advice ✅

**Goal:** move from recording the past to guiding the next decision — lightweight, rule-based, not a heavy AI advisor.

Scope delivered ([D36](DECISIONS.md)):
- **Budget vs actual**: per-category budgets (`categories.budget_amount`, reserved since Phase 1) got a write path (`POST /categories/{id}/budget`) + an inline budget editor; a variance view with bars that turn amber/red as actual approaches/exceeds the budget.
- **Overspend nudges** — three **deterministic, LLM-free** rules in `app/services/insights.py`: **over_budget** (month spend over the category budget), **spend_up** (category up ≥25% *and* ≥€20 vs last month), **paid-but-unused subscription** (a flagged/stale sub). Spend reuses the shipped `close` aggregation; staleness reuses `subscriptions.annotate`.
- **Insights, persisted + dismissable** — `POST /insights/generate` derives + upserts into a new `insights` table (keyed `(user, kind, month, subject)`), preserving a user-owned `dismissed` flag across regeneration; `GET /insights` + `POST /insights/{id}` to dismiss. Recomputable on demand.
- **Insights feed** on the Dashboard **and** a dedicated **`/advice` page**; the disabled sidebar placeholder is now a live entry.

Status: **shipped.** Backend tests **207 → 222**. No new model dependency; $0 marginal cost — every figure is computed in code, extending [D1](DECISIONS.md) to guidance.

---

## v0.5 — Ask chatbot (NL Q&A) ✅

**Goal:** let the user *ask* their money questions in plain language — "which day did I spend the most this
month?", "what do I buy most at Pingo Doce?", "send me the CSV for 1–18 Oct", "how much went to Groceries vs
last month?" — on top of the same one ledger, not just read dashboards.

Scope — **Slice 1 shipped (v0.5.0)**, see [D40](DECISIONS.md), [Round 10](feedback-notes.md):
- ✅ **Tool-calling architecture** — the LLM selects and parameterises **analytics functions that compute every
  number in code** (`app/services/analytics.py`, pure + unit-tested; extends [D1](DECISIONS.md) "the AI never does
  the math" to Q&A). Never free-form arithmetic, never text-to-SQL.
- ✅ **Grounded + direct answers** — natural language (no tool jargon), declines out-of-scope questions without
  inventing a figure, no app-navigation nagging.
- ✅ **Rich inline results** — receipt images inline (→ lightbox), a transactions table + **Download CSV** for a
  date range, an expandable grouped-by-vendor expense list, named products + a "most bought" tool.
- ✅ **Honest subscription reasoning** — `subscription_candidates` reuses Refund Hunter's eligibility (cash + one-off
  consumption never count) and cross-references the user's ledger categories; flags candidates only within one month.
- ✅ **Evaluation built-in (Slice 2)** — see [D41](DECISIONS.md). A chatbot eval harness over a **committed
  synthetic** fixed ledger (`backend/eval/chatbot/`, `scripts/eval_chatbot.py`): deterministic *(question,
  ledger) → exact answer* graded in **code**, **tool-selection accuracy** (the key metric), and a **refusal**
  set. Offline `--check` is gated in CI; the live gpt-5-mini run is gated locally. On the fixed set:
  tool-selection 18/18, answer-correctness 18/18, refusal 5/5. Backend tests 262 → 272.
- ✅ **Slice 3** — see [D42](DECISIONS.md). A **calibrated LLM-as-judge** for prose faithfulness
  (`services/chat_judge.py`; calibrated vs human-checked labels in `eval/chatbot/calibration.json` →
  `CALIBRATION.md`: 100% agreement, 100% recall on catching unfaithful → TRUSTED; live prose 18/18 faithful)
  **+ a response cache** (`services/chat_cache.py`) keyed on a ledger-state fingerprint, so a repeated
  question on unchanged data skips the model and self-invalidates on any change. Backend tests 272 → 287.

Status: **✅ complete** — v0.5 shipped in three slices (chatbot, eval harness, calibrated judge + cache).

---

## v0.5.3–v0.5.4 — Locale-safe parsing & honest public numbers ✅

**Goal:** a receipt must never vanish from a measurement, and every public claim must match what has actually been measured.

Scope delivered:
- **Locale-tolerant number parsing** (`'32,95'` → 32.95), and a malformed read can't crash extraction ([CHANGELOG](CHANGELOG.md) 0.5.3).
- **A model matrix that survives a single-model re-measure**, reports failed reads, and records how each row was measured ([D43](DECISIONS.md)). The local model is **90.1%** over all 26 receipts.
- **Public-page corrections:** claims, quick start, version strings, and a frontend build in CI.

Status: **shipped.** Backend tests **287 → 310**.

---

## v0.5.5 — Real Revolut PDF statements ✅

**Goal:** a real bank PDF imports correctly, not just a synthetic one.

Scope delivered ([D44](DECISIONS.md), [Round 11](feedback-notes.md)):
- **Revolut PDFs read in code** (English and Greek), accepted only if they match their own printed totals.
- **Re-upload protection across languages and formats**, and the model path repaired for other banks' PDFs.
- **Undo for Unmatch**, and possible matches from an unmatched expense's name ([D45](DECISIONS.md)).
- **Named recipients:** a Revolut transfer that names a person counts as a third party ([D45](DECISIONS.md)).

Status: **shipped.** Backend tests **310 → 329**.

---

## v0.5.6 — Ask: summary plus cards ✅

**Goal:** an answer you can read at a glance, shaped by real use.

Scope delivered ([D46](DECISIONS.md), [Round 11](feedback-notes.md)):
- **One or two sentences, then cards drawn by the code:** ranked bars, a month comparison and expense lists, with detail on click.
- **Correct "most expenses" and VAT:** a count per day, and no single rate for a mixed receipt.
- **The tester's real questions in the eval:** 22 answerable + 5 refusal.
- **Ask's cost and latency tracked** on Model & Evals, beside its accuracy ([D47](DECISIONS.md)).
- **Every total opens to its rows**, and an unknown category is never reported as €0 ([D48](DECISIONS.md)).
- **Clickable accuracy tiles**, one-vendor cards, and supermarkets categorized by rule ([D49](DECISIONS.md)).

Status: **shipped.** Backend tests **329 → 373**.

---

## v0.5.7 — One accuracy number, and a skimmable README ✅

**Goal:** one headline number that can't drift, and a front page a reader can scan.

Scope delivered ([D50](DECISIONS.md)):
- **One read path for both eval scripts,** every matrix row re-scored on current code, and badges generated from the metrics.
- **README restructured,** with full setup moved to `docs/SETUP.md`.
- **Corrected docs:** privacy (Ask and Sentry), the gate's coverage, and the Ask cache.

Status: **shipped.** Backend tests **373 → 376**.

---

## v0.5.8 — A locked test set, and published numbers a test checks ✅

**Goal:** a score on receipts the pipeline has never seen, and public figures that can't quietly drift from their results.

Scope delivered ([D51](DECISIONS.md), [D52](DECISIONS.md), [D53](DECISIONS.md)):
- **A held-out test set** of 9 new receipts, plus a separate VAT-per-rate score.
- **Nine models compared** on the development set and seven on the test set, with the prompts unchanged and every row dated.
- **Corrected costs:** the price table now matches the providers' lists, so Opus is about 13× `gpt-5-mini`, not 38.5×.
- **A test that fails** when the README or a model page stops matching its results.

Status: **shipped.** Backend tests **376 → 486**.

---

## v0.5.9 — Honest wording, from an outside review ✅

**Goal:** public claims no stronger than their evidence. No figure changed.

Scope delivered: the Refund Hunter's template default stated, the Opus cost explained, Ask's overall labelled, the judge's and the safety net's limits stated, the judge's badge generated from its result, and n8n's setup bound to localhost.

Status: **shipped.** Backend tests **486 → 493**.

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

## Open gaps (found 2026-11-05, not yet scheduled)

- **A saved monthly close.** ⬜ `GET /close` computes the summary and the Close button only confirms it on screen: no close record is stored and the month isn't locked, so later edits change a "closed" month. Build it or keep the summary wording, decided after a real timed close.
- **A timed month-end.** ⬜ The "minutes, not hours" target has no measurement yet (`problem-statement.md`).
- **A held-out accuracy number.** ✅ `eval/test/` holds 9 new receipts, frozen before any model read them and scored with the supermarket rules in place ([D51](DECISIONS.md)). It's small and narrow, so it should grow.
- **A fair test of Haiku 5.5 on unseen November receipts.** ⬜ It's one field ahead of `gpt-5-mini` on the 26, tied on the 9, and cheaper and faster, but those sets helped pick it, so they can't confirm it ([D53](DECISIONS.md)). Score November's receipts before any prompt change, then decide.
- **Separate provider settings for receipts and Ask.** ⬜ Ask, the bank PDF import and the refund emails all branch on one `LLM_PROVIDER`, so receipts can't move to Haiku without this.
- **A shared secret on the n8n webhook.** ⬜ It has no login today. Do it in the demo step, when n8n is revived anyway: it means re-importing the workflow and re-testing Gmail. Recreate any running container bound to `127.0.0.1` at the same time.
- **AI-written refund emails on OpenAI.** ⬜ Only the Anthropic provider uses a model today, so the default setup uses the template. It's a new feature, so build it with the separate provider settings.
- **A bigger, harder judge test set.** ⬜ 14 examples with planted errors and the tester's own labels is thin. Add real slips, more examples, and ideally a different model as judge.
- **Review the VAT consistency tolerance.** ⬜ `_vat_inconsistent` allows the larger of €1 or 10% of the total, which is loose on large receipts and assumes one chain's loyalty discounts. Revisit it with November's data, because tuning it now would change the gate after the test set was locked.
- **Plan for `gpt-5-mini`'s deprecation.** ⬜ OpenAI lists `gpt-5-mini` and `gpt-4o` as deprecated and recommends GPT-5.6 Terra, with no shutdown date found as of 2026-11-06. Ask uses `gpt-5-mini` too, so it needs its own comparison on the chatbot eval.
- **Why the local model's score moved.** ⬜ 90.1% to 97.2% between two runs, across two Ollama versions ([D53](DECISIONS.md)). A repeat on one version would separate the version from chance: free, about 5 hours.
- **Duplicate check by ATCUD.** ⬜ After November is scored, since it needs a prompt change: every Portuguese receipt prints a unique ATCUD code, a far stronger duplicate key than vendor + total + date ([D49](DECISIONS.md)).
- **A "paid by transfer" option.** ⬜ A purchase paid by bank transfer has no honest label: cash overstates the cash subtotal, and card leaves the row unreconciled at every close because transfers never match a receipt (Round 11).
- **A faster model for Ask.** ⬜ After November: compare models on the chatbot eval, since Ask takes about 10 seconds an answer ([D47](DECISIONS.md)).
- **Ask's cache ignores the date.** ⬜ A question like "this month" can repeat an earlier answer until the ledger changes or the backend restarts.
- **An outside tester.** ⬜ All feedback rounds so far are self-tests.
- **Fewer correct reads sent to review.** ⬜ The gate holds back 52% of correct reads because model confidence is poorly calibrated ([D30](DECISIONS.md)).

---

## Planned improvements (from testing feedback)

- **Per-line VAT.** ✅ Built — an `expense_line_items` table holds one VAT rate per line, so a mixed-rate receipt (e.g. 6% + 23%) is summed per rate in code instead of flattened to its dominant rate (see [D12](DECISIONS.md#d12--per-line-vat-a-receipt-can-hold-multiple-rates-design--r2)). Mechanism verified end-to-end against live Supabase; a real gpt-4o read of a mixed-rate receipt photo is the remaining confirmation step.
- **Duplicate detection at upload.** ✅ Built — `/extract` checks for an existing row with the same vendor + amount + date and routes a match to the review queue with an in-app warning, before anything posts (see [D13](DECISIONS.md#d13--flag-duplicates-at-upload-before-they-post-r2)).
- **LLM-assisted categorization.** ✅ Built — rules first, gpt-4o fills unknown vendors (Continente/Pingo Doce → Groceries), validated against the category list; added a Tobacco category (see [D15](DECISIONS.md)).
- **Extraction robustness (Round 3).** ✅ Built — printed IVA table as VAT source of truth, discount handling, estimated VAT when none is printed, date year-repair + re-read, net-vs-gross correction, server-side auto-rotation, and a self-consistency guardrail + retake flow (see [D14–D21](DECISIONS.md)). Backend tests 53 → 80.
- **Bank statements & reconciliation workbench (Round 4).** ✅ Built — PDF import, Revolut-aware CSV import, statements as first-class entities, collapsed exceptions, and a hand-drivable reconciliation popup (match / unmatch / not-a-match / no-receipt / re-scan) with believable suggestions only (see [D22–D25](DECISIONS.md)). Backend tests 80 → 97.
- **Extraction-accuracy eval harness.** ✅ Built (v0.2.5) — a labelled receipt set + `scripts/eval_extraction.py` gives a real field-level accuracy number (93% on gpt-5-mini); see [D26](DECISIONS.md) and `backend/eval/RESULTS.md`. It drove the model upgrade in [D27](DECISIONS.md).
- **Refund Hunter detection accuracy & transparency (Round 8).** ✅ Built — subscription detection now excludes non-purchase bank lines (top-ups/transfers/exchanges, reusing `is_reconcilable`) and one-off retail categories, requires **≥3** same-amount charges (two is a coincidence; no more annualising a single gap into a bogus €520/yr), and prunes stale auto-detections on re-run. Each subscription shows its charge dates + a "view charges" snapshot of the exact bank/CSV rows. Plus a cross-cutting fix so modals always render centered (portal to body). See [D37](DECISIONS.md), [feedback-notes.md](feedback-notes.md).
- **Idempotent bank re-upload + spending breakdown (Round 9).** ✅ Built — re-importing a statement that overlaps a previous one now adds only the genuinely-new rows (count-aware fingerprint on date + amount + description + balance) and preserves existing reconciliation, instead of duplicating the overlap. A new **Spending breakdown** (by vendor, and bank transfers split into third parties sent/received vs own-Revolut movements) is reachable from Reconciliation and the Ledger and drills to each transaction, plus a **"View CSV"** of a statement's raw source rows. See [D38](DECISIONS.md)/[D39](DECISIONS.md), [feedback-notes.md](feedback-notes.md).
- **Read-twice-and-compare** consensus mode. ⬜ Deferred option for maximum reliability on the hardest (crumpled + rotated) receipts.
- **`claude-opus-4-8` eval comparison.** ✅ Built — a column in `backend/eval/MODELS.md`, frozen at n=20 (see [D31](DECISIONS.md)).
- **Full measurement-receipt provenance on eval numbers.** 🚧 Partly done: `MODELS.md` now carries a per-model measurement record ([D43](DECISIONS.md)). `RESULTS.md`, the chatbot results and the README badges don't carry the full record yet. `eval_extraction.py` now reports failed reads the same way. The goal: give every published eval figure an explicit state label (*measured* / *declared* / *no-data-with-a-cause*) and a complete measurement receipt (command · machine · date · commit · artifact hash), extending the provenance `RESULTS.md`/`MODELS.md` already carry (command + run date + model, and informal "frozen n=20" / "—" gaps). The *pipeline* already refuses to silently drop a receipt ([0.5.3] / [CHANGELOG](CHANGELOG.md)); this makes the *reporting* layer equally explicit, so an unmeasured number is a declared gap with a cause, never a silent omission. Low risk, not urgent.

## Future work

Not committed, but the natural directions: a mobile app, support for **more banks** (more CSV formats / open-banking), and **more languages / locales** for receipts and VAT rules. See the README's *Future work* section.

- **Invoice / PDF-receipt support.** Surfaced in testing (2026-10-24): uploading an online-payment **invoice** (net line amounts + a separate tax line) correctly trips the self-consistency guardrail ([D21](DECISIONS.md)) because the receipt pipeline assumes each line amount is **gross** (VAT-inclusive), as supermarket receipts print. The read was still correct (total + vendor + category right, and a prompt-injection line was ignored — [D32](DECISIONS.md)); it just can't auto-post. A dedicated path — render a PDF page to an image, then extract with **net-aware** VAT handling — would make invoices first-class on the receipt side (today PDFs are accepted only for bank statements). Not a bug; a scope extension.
