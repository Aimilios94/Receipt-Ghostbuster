# Receipt Ghostbuster — Handoff Notes (read this first)

> ⚠️ **The sections below under "Original greenfield brief" are HISTORICAL** (from before
> any code existed). For the current state, read **"RESUME HERE" first.** The project is
> no longer greenfield — Phase 1 and Phase 2 are built, working, and on GitHub.

---

## 🟢 RESUME HERE — current status (as of 2026-10-19, day 7 — shipped v0.2.6, v0.3.0 + CI)

**Day 7 shipped three things, all committed and pushed to `main`:** a real testing fix (**v0.2.6**),
a new milestone (**v0.3.0 — LLM Observability & Evaluation**), and a **CI regression gate**. Backend
tests **109 → 128**, frontend build clean, verified end-to-end against live Supabase.

**What day 7 shipped (newest first):**
- **CI regression gate (commit `0ec19cb`):** `.github/workflows/ci.yml` runs on every push/PR —
  installs backend deps, runs `pytest -q` (128), then smoke-runs the eval harness in **mock** mode
  (no secrets, no personal data) so the whole pipeline is exercised offline. Needed a committed
  fixture because the real `receipts/` + `labels.json` are git-ignored: added a `--receipts` flag to
  `scripts/eval_extraction.py` + `backend/eval/fixtures/mock.jpg` + `backend/eval/labels.mock.json`.
  **First run GREEN in 29s.** `gh` CLI is present + authed (`gh run watch <id> --exit-status`).
- **v0.3.0 — LLM Observability & Evaluation (commit `ec02398`, see DECISIONS D30):** the production-LLM
  layer around the existing eval + guardrails.
  - **Instructor structured outputs** — the vision read parses through `instructor.from_openai/anthropic`
    (`response_model=ExtractionResult`, `instructor_max_retries`) with a tolerant **raw-parse fallback**
    (records `fell_back`). Prompt unchanged; **eval 93% → 98%**. ⚠️ Installing instructor **downgraded
    openai 3.24 → 3.3.0** (still satisfies `>=1.50`, verified working). ⚠️ **Reads are now SLOWER**
    (~35–50s with Instructor/tools on gpt-5-mini vs ~20s raw; a landscape receipt doing multiple
    orientation reads can take 1–2 min — by design, not a hang).
  - **Per-call tracing** (`services/llm_trace.py`) — latency, tokens, estimated cost (`price_usd` table)
    and the gate outcome persisted to a new **`llm_traces`** table (schema applied live). Services stay
    DB-free; the router persists. `extract_receipt` now returns a **3-tuple `(result, oriented, trace)`**.
  - **One measured gate** (`services/gating.py::decide_gate`) — the routing logic was factored out of
    `routers/extract.py` into a pure function used by **both** `/extract` and the eval harness.
  - **Guardrail + calibration metrics** (`services/eval_metrics.py`) — the eval now reports false-auto-post
    rate, over-review rate and confidence calibration → `RESULTS.md` + committable `eval/metrics.json`.
  - **Model & Evals dashboard** at `/model-evals` (sidebar `Icon.gauge`) reading `GET /metrics/eval` +
    `GET /metrics/llm`. Built with existing CSS/SVG (no charting dep).
  - **Optional LangSmith** — `wrap_openai/anthropic_if_enabled` (soft, env-gated) + `scripts/langsmith_eval.py`
    (uploads the set as a LangSmith Dataset, runs an Experiment). **Off by default**; opt-in via `LANGSMITH_TRACING`.
  - **Honest findings the eval surfaced (real, not invented):** gpt-5-mini's self-reported confidence is
    **poorly calibrated** (0.7–0.8 reads 100% correct, 0.8–0.9 only 75%), so the gate **over-reviews ~70% of
    correct reads**; the 1 wrong read (a date off by a day that reconciles) auto-posted because no guardrail
    can catch a plausible self-consistent wrong date.
- **v0.2.6 — robust duplicate detection + self-contained receipt viewer (commit `063534f`, D29, Round 6):**
  duplicate detection now matches on **vendor (brand-prefix) + total-to-the-cent within ±30 days**, not
  exact date (the date is the most-misread field); fixed a stale shadow `find_duplicates`. Plus a shared
  `components/ReceiptLightbox.jsx` where **Esc / ✕ / backdrop close only the image**, not the dialog behind
  it (rolled out to all 6 lightboxes).

### 👋 Message to the next agent (read this)
Everything is committed and pushed (`main` at `0ec19cb`); working tree clean, CI green. The user was about
to do **manual testing** of day-7 work at the end of the session — next session likely **starts with their
testing feedback**, or moves to **v0.4 — Advice**. When you resume:
1. **Read, in order:** this RESUME section → the auto-memory status file (path at bottom) → **DECISIONS.md**
   (now D1–D30) → **feedback-notes.md** (Rounds 1–6) → the v0.3.0 plan `C:\Users\aimilios\.claude\plans\silly-dazzling-muffin.md`.
   New v0.3.0 modules to understand: `services/llm_trace.py`, `services/gating.py`, `services/eval_metrics.py`,
   `routers/metrics.py`, `pages/ModelEvals.jsx`, `scripts/langsmith_eval.py`.
2. **Start the servers** (commands below). **Provider is OpenAI `gpt-5-mini`** — reads are **slow now
   (~35–50s, up to ~2 min for a rotated receipt)** because of Instructor's structured-output mode; this is
   accuracy-for-latency, by design. Run **ONE** backend uvicorn, **no `--reload`** (it may show as a
   parent+child pair — that's ONE server, fine; the bad case is two *independent* instances). Supabase uses a
   **per-thread** client. **Check the two 7-day expiries** before any demo (memory `demo-prep-7day-expiries`).
3. **Do NOT re-litigate settled decisions (D1–D30).** Keep the **authenticity rule**: real testing → real
   feedback-notes → real decisions; never invent feedback or metrics. v0.3.0 was an *engineering* milestone,
   so it has **no** feedback round (D30 carries the "why") — that was deliberate, don't add a fake one.
4. **User preference (now in memory `no-job-seeking-framing-in-docs`):** committed/user-facing docs must NOT
   describe the project as a job-seeking portfolio or name target roles — present it as engineering on its merits.
5. **Open items (user's choice next):**
   - **v0.4 — Advice** (budget vs actual, overspend nudges, insights feed) — the next planned milestone.
   - **Auto-post a cent-perfect reconciling read** — the eval now quantifies the over-review cost; the user
     deferred this (risk: a self-consistent-but-wrong read auto-posting). Decide with the user.
   - **`claude-opus-4-8` / Claude Sonnet·Haiku eval comparison** — pending Anthropic credits (currently out).
     Offered but not built: add `--provider/--model` flags to `scripts/langsmith_eval.py` so model comparison
     in LangSmith is one command per model (the offline harness already has those flags).
   - Grow the labelled eval set (11 receipts is small) for a more robust number.
6. **LangSmith for real data (user wants this for evidence):** set `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY`
   in `backend/.env`, restart backend → traces appear in their LangSmith project; `python scripts/langsmith_eval.py`
   creates an Experiment. Privacy: with it on, receipt images/prompts go to LangSmith's cloud (user accepted).
7. **Note:** real test receipts live in the PARENT folder `C:\Users\aimilios\Desktop\CV-creation\` (git-ignored
   copies in `backend/eval/receipts/`). Ledger currently = **16 real expenses** + `octomber-2026.csv`. The
   Model & Evals dashboard has **1 real trace** on it (from an end-to-end verification upload).

---

## 🟢 RESUME HERE — prior status (as of 2026-10-18, day 6 — Round 5, shipped v0.2.5)

**Day 6 continued (Round 5) = measured extraction accuracy, then acted on it. Shipped as `v0.2.5`.
Backend tests 97 → 99 passing, frontend build clean, all verified against live Supabase.** This was the
queued "eval harness" step — and the harness immediately exposed real problems that drove a model upgrade.

**What Round 5 shipped (see DECISIONS D26–D28 + feedback-notes Round 5):**
- **Extraction-accuracy eval harness (D26):** `backend/scripts/eval_extraction.py` runs the SHIPPED
  pipeline (`extraction.extract_receipt` + `receipt_fields.compute`) over a hand-labelled set and scores
  each field. Dataset in `backend/eval/`: `receipts/` (11 real full-res receipts) + `labels.json` are
  **git-ignored (personal data)**; `labels.example.json`, `README.md`, `.gitignore`, and aggregate
  `RESULTS.md` are committed. Per-image reads cached (`eval/.cache/`, keyed by model); flags
  `--provider` / `--model` / `--refresh` / `--limit`. Currency is NOT scored (€ symbol, not ISO text).
- **MODEL SWITCH gpt-4o → gpt-5-mini (D27) — the big one.** User uploaded a real 3-rate Continente
  receipt; it showed only 2 rates with amounts fudged to the total. Diagnosed (per-model, full-res): NOT
  a logic bug — **gpt-4o mis-reads dense 3-rate VAT tables**; gpt-5-mini/o4-mini read them perfectly.
  `config.py` default `openai_model = "gpt-5-mini"` (the `.env` does NOT set OPENAI_MODEL, so the default
  applies). `services/extraction.py::_extract_openai` auto-detects reasoning models (`_is_reasoning_model`:
  gpt-5*/o1/o3/o4*) → `max_completion_tokens: 8000`. **Eval 84% → 93%** (VAT amount/rate 67/56% → 89/89%).
- **Read every orientation (D27):** the auto-rotation no longer early-breaks on the first "strong" read
  (a sideways read can look confident on a fragment) — it reads all orientations incl. 180° and keeps the
  most complete. Fixed a €4.48 receipt that read €24.99.
- **Retake prompt trusts reconciliation (D27):** a read whose printed VAT table (or items) ties to the
  total to the cent is trusted over the model's self-reported confidence → no more "retake" nag on a
  correct read (it still goes to review for a quick confirm). `routers/extract.py`.
- **Uber Eats → Dining (not Transport):** `categorization.py` — "uber eats"/"glovo"/"bolt food" rule
  before the generic "uber" (rides). Category accuracy 90% → 100%.
- **"No bank line" (D28):** expense-side mirror of the bank's "No receipt". New `expenses.no_bank_match`
  (schema applied live), `POST /reconcile/no-bank-match`, button in ReconcileResultModal. Lets the user
  clear a card expense that has no bank line so the Unmatched list reaches a clean state.

### 👋 Message to the next agent (read this)
Everything Round 5 is committed and pushed as `v0.2.5`. When you resume:
1. Read this RESUME section + the auto-memory file (path at bottom) + **DECISIONS.md** (now D1–D28) and
   **feedback-notes.md** (Rounds 1–5). Keep the **authenticity rule**: real testing → real
   feedback-notes → real decisions. Never invent feedback or metrics.
2. Start the servers (commands below). **Provider is now OpenAI `gpt-5-mini`** (reasoning model — it's
   SLOWER, ~20s/read, up to ~90s for a rotated receipt; this is accuracy-for-latency, by design). Run ONE
   backend uvicorn, **no `--reload`**. Supabase uses a **per-thread** client — don't revert to the
   `@lru_cache` singleton. **Check the two 7-day expiries** before any demo (Supabase pause, n8n Gmail
   OAuth — memory `demo-prep-7day-expiries`).
3. **Do NOT re-litigate settled decisions (D1–D28).** Confirm priority with the user before large new
   directions.
4. **Open items (good next moves, beyond manual testing):**
   - **`claude-opus-4-8` eval comparison** — run `python scripts/eval_extraction.py --provider anthropic`
     once Anthropic credits are topped up (currently out of credits), add the column to `RESULTS.md`/README.
   - **Grow the eval set** — more labelled receipts (esp. hard/rotated) make the 93% more robust; the
     harness + labelling format are ready (`backend/eval/README.md`).
   - **Read-twice-and-compare** consensus mode for the hardest crumpled+rotated photos (deferred option).
   - Optional: let a cent-perfect reconciling read **auto-post** (skip review) to cut friction — the user
     was asked, left open (risk: a self-consistent-but-wrong rotated read auto-posting).
   - Then **v0.3 — Advice** (budget vs actual, overspend nudges, insights feed) + a hosted demo.
5. **Note:** real test receipts live in the PARENT folder `C:\Users\aimilios\Desktop\CV-creation\`
   (`1000017779.jpg`, `octomber-2026.csv`, etc.) — the eval set in `backend/eval/receipts/` is a git-
   ignored copy of them. The user drives real testing. Two unmatched Pingo Doce €48.24 in his ledger are
   the SAME receipt uploaded twice — a true duplicate he may want to delete.

---

## 🟢 RESUME HERE — prior status (as of 2026-10-18, day 6 — Round 4, shipped v0.2.4)

**Day 6 (Round 4) = a big real-testing session (user driving) → bank-statement import + a hand-drivable
reconciliation workbench, shipped as `v0.2.4`. Backend tests 80 → 97 passing, frontend build clean,
all verified in-browser against live Supabase.** The user imported a real **Revolut CSV**
(`octomber-2026.csv`) and re-read real receipts; every issue was fixed and verified the same day.

**What day 6 shipped (grouped; see DECISIONS D22–D25 + feedback-notes Round 4):**
- **PDF bank import (D22):** Import dialog accepts a text-based PDF as well as CSV — `pdfplumber` text
  extraction → gpt-4o structuring (reads only; amounts/dates re-parsed + signed in code) → deterministic
  regex fallback. Scanned PDFs rejected clearly. `backend/app/services/pdf_import.py`.
- **Revolut-aware CSV import:** `services/csv_import.py` auto-detects column names (incl. `Completed
  Date`, debit/credit) across EN/PT/ES/DE, sniffs the delimiter, strips the time off `D/M/YYYY HH:MM`
  dates, skips PENDING/REVERTED rows, never stores a blank date. Import errors now return 400/502 (with
  CORS headers) — fixed the "can't reach backend" that was really a 500 on an empty date.
- **Top-ups/transfers aren't purchases (D23):** `reconciliation.is_reconcilable` — only money-out,
  non-transfer lines need a receipt (detected via raw `Type` or description). Used in reconcile +
  `exceptions.unmatched_bank` + statement needs-receipt counts.
- **Bank statements section (D24):** new `bank_statements` table + `statement_id` FK on
  bank_transactions (schema applied live). New page `/bank-statements` (list: file, upload date, period,
  Spent/Received/Net, needs-receipt, delete → cascade; click → transactions detail). Dashboard +
  Reconciliation collapse unmatched bank lines into **one row per statement** (NEW-flag via
  `lib/useSeen.js`). Endpoints `GET /bank/statements`, `/bank/statements/{id}/transactions`, `DELETE`.
- **Reconciliation workbench (D25):** `components/ReconcileResultModal.jsx` — opens after Run
  reconciliation OR via a new **Match manually** button (`GET /reconcile/state`, no auto-run). Matched
  receipt↔bank pairs (View receipt + View transaction = exact CSV row), unmatched expenses with a
  **believable** suggestion (same vendor OR exact amount within a few days — NOT closest-by-amount) +
  **Match → / Not a match / Others**, and bank payments needing a receipt with a **No receipt** action
  (`no_receipt` flag → leaves the cycle). Endpoints `POST /reconcile/match · /unmatch · /no-receipt`.
- **Replace receipt photo (re-scan):** `EditReceiptButton.jsx` next to every View receipt (reconcile
  popup, ExpenseDetailModal, DrillModal) → `POST /expenses/{id}/rescan` re-reads a new photo and updates
  the expense (field math shared via `services/receipt_fields.py`).
- **Fixes:** printed IVA table now accepted within a RELATIVE tolerance and scaled to the exact total
  (fixed a Pingo Doce showing net 37.50 under a 48.24 total — extends D14, in receipt_fields AND
  extract.py); **per-thread Supabase client** (`supabase_client.py`) — killed the transient Windows
  `WinError 10035` "can't reach backend" under concurrent load; frontend `retry: 2`.
- **Data:** sample bank statements + the 5 sample subscriptions were PURGED at the user's request — the
  ledger now shows only his real uploads (17 expenses + `octomber-2026.csv`). **Reload before a recruiter
  demo:** `scripts/load_sample_data.py` + `scripts/load_phase2_demo.py`. Reconcile links were reset to a
  clean slate.

### 👋 Message to tomorrow's agent (read this)
Everything day 6 is committed as `v0.2.4`. When you resume:
1. Read this RESUME section + the auto-memory file (path at bottom) + **DECISIONS.md** (now D1–D25) and
   **feedback-notes.md** (Rounds 1–4). Keep the **authenticity rule**: real testing → real
   feedback-notes → real decisions. Never invent feedback or metrics.
2. Start the three servers (commands below). **Check the two 7-day expiries first** (Supabase pause, n8n
   Gmail OAuth — memory `demo-prep-7day-expiries`). Run ONE backend uvicorn, **no `--reload`**. If a
   recent frontend change doesn't show, restart `npm run dev` (stale HMR). Provider = OpenAI gpt-4o.
3. **Do NOT re-litigate settled decisions** (D1–D25). Confirm priority with the user before large new
   directions. The backend talks to Supabase with a **per-thread** client now (don't revert to the
   `@lru_cache` singleton — it caused Windows socket errors under load).
4. **Open items, in the user's chosen order:**
   - **Extraction-accuracy eval harness** (`backend/scripts/eval_extraction.py` + labelled receipts) →
     the README "Results" number. Authentic, not invented.
   - Optional refinement: preserve the printed per-rate VAT *exactly* on scaled receipts (scale NET not
     gross) — currently within ~2¢ on a crumpled-digit misread; deferred.
   - Then **v0.3 — Advice** (budget vs actual, overspend nudges, insights feed) + a hosted demo.
5. **Note:** test receipts live in the PARENT folder `C:\Users\aimilios\Desktop\CV-creation\`
   (`1000017846.jpg`, `octomber-2026.csv`, etc.) — NOT in the repo. The user drives real testing.

---

## 🟢 RESUME HERE — prior status (as of 2026-10-15, end of day 5)

**Day 5 = a big Round-3 real-receipt testing session (user driving) → ~20 extraction-robustness
fixes, shipped as `v0.2.3` and pushed to GitHub. Backend tests 53 → 80 passing, frontend build
clean.** The user uploaded a batch of hard receipts (3-rate, discounted, no-VAT, sideways,
crumpled); every issue was fixed and verified the same day against live Supabase.

**What day 5 shipped (grouped; see DECISIONS D14–D21 + feedback-notes Round 3 for the full record):**
- **LLM-assisted categorization (D15):** gpt-4o suggests a category during extraction — rules run
  first, the suggestion fills unknown vendors (Continente/PD OLAIAS/Pingo Doce → Groceries),
  validated against the category list. Added a **Tobacco** category + `POST /expenses/{id}/category`
  + an **editable Category dropdown in the Ledger**. (Closed the last DECISIONS "Planned" item.)
- **Printed IVA table = VAT source of truth (D14):** extraction transcribes the printed VAT summary
  (`tax_lines`) and uses it when it ties to the total — read, never guess.
- **Discounts (D17):** POUPANÇA / Special Offer / Desconto are never products; `total` is the amount
  **paid after** discount; discounted lines are scaled to the amount paid so VAT is on what was paid.
- **Estimated VAT (D18):** when a receipt prints no VAT (Uber Eats, tills), gpt-4o estimates the
  standard PT rate per product (food 13 / drinks 23 / groceries 6), computed in code, routed to
  review and shown as **amber "suggested"** fields with a tooltip. Real **0%** (tobacco) is a
  captured answer — no longer flagged "missing VAT".
- **Dates (D16):** a focused **date re-read** pass + a deterministic **year-repair** (snap a misread
  year to the recent one, never the future, force review with "corrected X→Y, confirm"). Learns the
  `Data Emissão` ISO date and the `YY-MM-DD` terminal line.
- **Amount = net + VAT (D19):** when the model reads the net/BASE line as the total, store the gross
  (fixed Auchan €3.77 → €4.18).
- **Server-side auto-rotation (D20):** **Pillow added** (`pip install Pillow --trusted-host pypi.org
  --trusted-host files.pythonhosted.org`). EXIF + landscape detect + re-read at 90/270/0 (180
  fallback), keep the best-reconciling orientation, **store the straightened image**. NOTE:
  `extraction.extract_receipt` now returns **(result, oriented_bytes)**.
- **Self-consistency guardrail + retake (D21):** when the printed VAT table and the item lines
  disagree per-rate, the read is flagged unreliable and **not auto-posted**; a **retake prompt** at
  upload and a **Retake photo** button in the review queue re-read a clearer shot. A
  **read-twice-and-compare** consensus mode was discussed and **deferred as a future option**.
- **UX polish:** Ledger columns Net·VAT·Total; reconciliation **exceptions are clickable → full
  detail + deletable**, sorted **newest-upload-first** with an unread **"NEW"** highlight; the detail
  popup reads **Net (total) · VAT (total) · Paid**; per-VAT-line net·VAT·total; 0% promoted in the
  rate picker; **duplicate-at-upload comparison popup** (Net/VAT/Total + view-receipt + discard/keep).

### 👋 Message to tomorrow's agent (read this)
Nothing is broken or mid-flight; everything day 5 is committed and pushed as `v0.2.3`. When you resume:
1. Read this RESUME section + the auto-memory file (path at bottom) + **DECISIONS.md** (now D1–D21) and
   **feedback-notes.md** (Rounds 1–3 are the live product-engineering record). Keep the **authenticity
   rule**: real testing → real feedback-notes → real decisions. Never invent feedback or metrics.
2. Start the three servers (commands below). **Check the two 7-day expiries first** (Supabase pause,
   n8n Gmail OAuth — memory `demo-prep-7day-expiries`). Run exactly ONE backend uvicorn, **no
   `--reload`**. If a recent frontend change doesn't show, the **vite dev server may have stale HMR**
   (it ran 3 days during day 5) — restart `npm run dev`. Backend reads OpenAI gpt-4o from `backend/.env`.
3. **Do NOT re-litigate settled decisions** (stack, phasing, hybrid n8n, draft-only, cash-excluded,
   per-line VAT bucket rounding, printed-table-as-VAT-truth, discounts-not-products, estimated-VAT,
   auto-rotation). Confirm priority with the user before large new directions.
4. **Open items, in the user's chosen order:**
   - **Extraction-accuracy eval harness** (`backend/scripts/eval_extraction.py` + labelled receipts
     the user supplies) → the README "Results" number. Authentic, not invented.
   - **Read-twice-and-compare** consensus mode (optional, deferred) if the user wants max reliability.
   - Then **Phase 3 — Advice** (budget vs actual, overspend nudges, insights feed) + a **hosted demo**.
5. **Honest limit (reinforces D9):** flat/well-lit receipts auto-post correctly; a **physically
   crumpled** receipt can still produce a confident-wrong read — the system now catches it (D21),
   routes to review, and lets the user edit/retake/delete. No prompt invents correct digits off
   creased paper. Test receipts live in the PARENT folder `C:\Users\aimilios\Desktop\CV-creation\`
   (`1000017808/10/11/79.jpg`, etc.), uploaded through the app UI.

---

## 🟢 RESUME HERE — prior status (as of 2026-10-13, end of day 4)

**Day 4 = Round 2 real-testing session (user driving) → per-line VAT + a batch of fixes, all shipped
as `v0.2.2`.** The user uploaded real mixed-rate Portuguese receipts; every issue was fixed and
verified the same day. **53 pytest pass, frontend build clean, verified end-to-end against live
Supabase.** Backend is running on :8000 with the **OpenAI** provider.

**What day 4 shipped (newest first):**
- **Duplicate detection at upload (D13):** `/extract` now checks the ledger for an existing row with the
  same vendor + amount + date (`repo.find_duplicates`). A match is forced into the review queue (never
  auto-posts) and the snap modal shows an in-app warning naming the existing expense. Response carries
  `duplicate_of`. Verified live.
- **Ledger ergonomics:** rows are **clickable → `ExpenseDetailModal`** (per-rate VAT + line items with
  amount/rate/VAT each + a totals row + grand-total strip + receipt image); a **receipt-thumbnail
  column** after Status; the **Status cell is a dropdown** (Posted / Needs review / Confirmed) backed by
  new `POST /expenses/{id}/status`.
- **Editing:** the review Edit form dropped the redundant single "VAT rate" field — all VAT now lives in a
  reusable **`VatLinesEditor`** (multi-rate, seeded with one line for single-rate receipts; amount = sum
  of lines). Dashboard drill-down rows got an **Edit** action (`ExpenseEditModal`, reuses the editor).
- **Post confirmation toast** now states what landed ("Posted CONTINENTE — €11.58 incl. €1.00 VAT added
  to your ledger").
- **Per-line VAT engine (D12):** `expense_line_items` table (one rate per line); `vat.vat_breakdown`
  sums VAT **bucket-first** (VAT on each rate's gross total) so it matches the printed Portuguese IVA
  summary to the cent; extraction reads per-line rates (Portuguese VAT-code/summary-table convention);
  expense `vat_amount` = per-rate sum, dominant rate kept for single-rate display. Migration applied to
  live Supabase via `scripts/apply_schema.py` (idempotent).
- **Extraction date fix (extends D7):** prompt prefers the top `DD/MM/YYYY` invoice date, ignores the
  bottom `YY-MM-DD` card-terminal line (a real "date in the future" misread). Reduces but doesn't fully
  eliminate date misreads on crumpled receipts — the date is editable in review as the fallback.
- **Data cleanup (user request):** deleted the 11 Phase-1 sample seed expenses + the 3 stale misread-2023
  test uploads from the LIVE DB. **The ledger now shows only the user's 8 real rows** (Oct-2026
  Continente/Pingo Doce uploads + one manual "Egyptian Restaurant"). The dashboard now opens on
  **October 2026**. ⚠️ Sample **bank transactions** + **Phase-2 subscription demo** data are STILL
  loaded (they power Reconciliation/Refund Hunter). **Reload expense samples before any recruiter demo:**
  `cd backend && ./.venv/Scripts/python.exe scripts/load_sample_data.py`.

### 👋 Message to tomorrow's agent (read this)
Nothing is broken or mid-flight; everything day 4 is committed and pushed as `v0.2.2`. When you resume:
1. Read this RESUME section + the auto-memory file (path at bottom) + **DECISIONS.md** (now D1–D13) and
   **feedback-notes.md** (Rounds 1 + 2 are the live product-engineering record). Keep the **authenticity
   rule**: real testing → real feedback-notes → real decisions. Never invent feedback or metrics.
2. Start the three servers (commands below). **Check the two 7-day expiries first** (Supabase pause, n8n
   Gmail OAuth — memory `demo-prep-7day-expiries`). Run exactly ONE backend uvicorn, **no `--reload`**
   (Windows orphans the port). The backend reads provider/keys from `backend/.env` (OpenAI gpt-4o).
3. **Do NOT re-litigate settled decisions** (stack, phasing, hybrid n8n, draft-only, cash-excluded,
   per-line VAT bucket rounding). Confirm priority with the user before large new directions.
4. **Open items, in the user's chosen order:**
   - **LLM-assisted categorization** — the last item in DECISIONS "Planned". Rules return "Uncategorized"
     for vendors like Continente/PD OLAIAS/Pingo Doce. Have the LLM suggest a category during extraction
     (it's already reading the receipt) or expand the keyword rules.
   - **Extraction-accuracy eval harness** (`backend/scripts/eval_extraction.py` + labeled receipts the
     user supplies) to fill the README "Results" number — authentic, not invented.
   - Possibly model the **discount / "Poupança"** line as a first-class concept (a receipt's items can
     sum above the amount paid — see the Pingo Doce `1000017701.jpg` case in feedback-notes R2).
   - Then **Phase 3 — Advice** (budget vs actual, overspend nudges, insights feed) and a **hosted demo**.
5. Test receipts live in the PARENT folder `C:\Users\aimilios\Desktop\CV-creation\` (`1000017700.jpg`,
   `1000017701.jpg` Pingo Doce 3-rate+discount, `1000017708.jpg` Continente 3-rate, `84/85`, etc.) —
   NOT inside the repo. Receipts are uploaded through the app UI.

---

## 🟢 RESUME HERE — prior status (as of 2026-10-12, end of day 3)

**Where we are:** Phase 1 + Phase 2 are complete and pushed. **Day 3 was a product-engineering
pivot:** we did NOT add Phase 3 yet. Instead we (a) set up the recruiter-facing **doc system**
(problem-statement, roadmap, DECISIONS, CHANGELOG, feedback-notes), (b) ran a real **Round 1
testing session** with the user driving, and (c) shipped every fix that surfaced. The repo now
*shows* a product-engineering process, not just a working app.

**GitHub:** https://github.com/Aimilios94/Receipt-Ghostbuster (branch `main`). Day 3 pushed.

### Why day 3 happened (context you need)
The user is building this as a **GitHub portfolio piece to land a product-engineer role**. He
gathered a doc framework (Problem→Evidence→Decision→Result + roadmap/changelog/feedback) and
asked us to make the repo prove he works that way. The **authenticity rule is sacred**: every
process artifact must trace to something real — the testing session IS the real feedback round;
no invented data, no fake metrics.

### What day 3 shipped (all tested in-browser, 0 console errors, 46 pytest pass, build clean)
- **Docs:** `problem-statement.md`, `roadmap.md`, `DECISIONS.md` (D1–D11), `CHANGELOG.md`,
  `feedback-notes.md` (Round 1). README rewritten to the PE structure (Process-links section,
  features-by-version, Results). `n8n/README.md` cleaned (user's scratch notes removed).
- **Dashboard drill-downs (D10):** every stat card + category row + "See all" opens the source
  expenses with receipt view + delete. `frontend/src/components/DrillModal.jsx` (new).
- **Extraction (D7/D9):** prompt now reads Portuguese **day-first** dates, handles rotation,
  extracts all line items; OpenAI `detail:"high"`. Fixed the "receipt from the future" false flag.
- **Confirmed-only ledger (D8):** `close`/`exceptions`/`reconcile` now exclude `pending_review`
  so posting a reviewed receipt actually updates totals (was a no-op).
- **Delete** expenses from drill-downs + ledger preview. **VAT-by-rate** breakdown (dashboard VAT
  card + clickable Ledger VAT total). **Edit form** got View-receipt + VAT-rate field. **Capture
  hint** on the snap screen. **Duplicate surfacing (D11):** badge + highlight + `?view=duplicates`
  filter + deep-link from the exception.

### 👋 Message to tomorrow's agent (read this)
Nothing is broken or mid-flight. Everything day 3 is committed and verified. When you resume:
1. Read this RESUME section + the auto-memory file (path at bottom) + **DECISIONS.md** and
   **feedback-notes.md** (they are the live product-engineering record).
2. Start the three servers (commands below). Backend reads OpenAI from `.env` — no flags.
   **Check the two 7-day expiries first** (see memory `demo-prep-7day-expiries`): Supabase may be
   paused, n8n Gmail OAuth token may be expired. Revive before testing.
3. **Open items the user chose to do next** (in priority order he implied):
   - **Per-line VAT** (decided to build — see DECISIONS "Planned" + roadmap). Needs a line-item
     table so a receipt can hold multiple VAT rates; sum per rate in code.
   - **Duplicate detection at upload** (flag before posting).
   - **LLM-assisted categorization** (Continente → Groceries; rules miss unknown vendors).
   - Then the **accuracy eval harness** (`backend/scripts/eval_extraction.py` + labeled receipts
     the user supplies) to fill the README "Results" number — authentic, not invented.
   - Eventually **Phase 3 — Advice**, and a hosted live demo.
Do NOT re-litigate settled decisions (stack, phasing, hybrid n8n, draft-only, cash-excluded).
Keep the authenticity rule: real testing → real feedback-notes → real decisions. Confirm with the
user before large new directions.

### Day 2 additions (newest first)
- **Editable/deletable review queue** (commit `4432dc2`): "Post" now works (was sending `{}` →
  422); review items are **editable** (fix vendor/amount/date/category before posting, e.g. a
  misread year); **Discard really deletes** now (was client-side only); **Ledger rows have a ×
  delete** button. New `DELETE /expenses/{id}`.
- **Extraction guardrails** (commit `5430614`): `services/validation.py` runs deterministic checks
  regardless of model confidence → unreadable (no total) prompts a retake (no row created);
  future/old date, low confidence, or line-items≠total → routed to review with reasons shown.
  Caught a real misread (model read a 2026 receipt's date as 2023 at 0.9 confidence).
- **OpenAI vision provider** (commit `8b729d8`): user added `OPENAI_API_KEY` + set
  `LLM_PROVIDER=openai` in `.env`; `openai` pkg installed in venv and in requirements.txt. Real
  receipt extraction VERIFIED (gpt-4o read vendor/total/date/VAT/line-items correctly). NOTE:
  Anthropic key is OUT OF CREDITS — that's why we switched; drafts still have a template fallback.
  pip in this sandbox needs `--trusted-host pypi.org --trusted-host files.pythonhosted.org` (SSL).

**What's built & verified:**
- **Phase 1 — backend:** FastAPI. Receipt extraction (vision LLM) + confidence gate, rules
  categorization, VAT math, bank CSV import, reconciliation engine, month-scoped exceptions,
  monthly close + extraction guardrails. **46 pytest tests pass** (`cd backend && ./.venv/Scripts/python.exe -m pytest -q`).
- **Phase 1 — frontend:** React + Vite + TanStack Query + Geist fonts. Dark dashboard built to
  the `Receipt Ghostbuster-selection.pdf` mockup. Screens: Dashboard, Review queue, Reconciliation
  (month picker), Monthly close, Ledger. Add-expense + Import-bank modals. Accessibility pass done.
- **Phase 2 — Refund Hunter:** subscription detection (`services/subscriptions.py`), flag/keep/
  cancel + savings, draft cancel/refund email (`services/refund_email.py`, LLM with template
  fallback), and **n8n → Gmail draft delivery working for real** (draft-only, never sends).
  Screens: `/refunds` page + DraftEmailModal. Dashboard recurring-charges card reads live data.
- **n8n:** dedicated Docker container `receipt-ghostbuster-n8n` on **http://localhost:5678**
  (volume `rg_n8n_data`). The "Refund draft to Gmail" workflow is IMPORTED + ACTIVE, Gmail
  credential connected and working. Workflows live in `/n8n/`. `N8N_WEBHOOK_URL` is set in
  `backend/.env` and `/health` reports `n8n_configured: true`.

**How to run the whole thing (3 terminals; Windows PowerShell):**
```
# 1) n8n (if the container is stopped)
docker start receipt-ghostbuster-n8n        # already exists; or see /n8n/README.md to create

# 2) backend  (DO NOT use --reload on Windows — it orphans processes that hold :8000)
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 3) frontend
cd frontend
npm run dev        # http://localhost:5173
```
Demo data: `cd backend && ./.venv/Scripts/python.exe scripts/load_sample_data.py` (Phase 1,
September) and `scripts/load_phase2_demo.py` (Phase 2 multi-month recurring history). Schema:
`scripts/apply_schema.py`.

**Known gotchas (IMPORTANT — these bit us today):**
- **Windows uvicorn:** `taskkill` by PID leaves orphan children holding :8000, and two uvicorn
  processes cause intermittent CORS/`ERR_FAILED` in the browser. To kill cleanly, use PowerShell:
  `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` → `Stop-Process` the uvicorn ones,
  then start exactly ONE. Never run with `--reload` here.
- **LLM provider = OpenAI (gpt-4o)** — set in `.env` (`LLM_PROVIDER=openai` + `OPENAI_API_KEY`).
  **Anthropic is OUT OF CREDITS** (don't switch back unless the user tops it up). `openai` pkg is
  installed in the venv. To `pip install` anything in THIS sandbox, add
  `--trusted-host pypi.org --trusted-host files.pythonhosted.org` (SSL cert error otherwise).
- **n8n container** is currently running with `-e N8N_LOG_LEVEL=debug` (turned on to debug Gmail).
  Fine to leave; recreate without it for quieter logs (volume persists the active workflow + creds).
- The **weekly-detection cron** workflow (`/n8n/detect-subscriptions-cron.json`) is imported but
  **won't publish** due to an n8n 2.x version/publish quirk — low priority, the manual "Run
  detection" button works. If needed: edit it in the UI, make a tiny change, Save, then Publish.
- A few **test Gmail drafts** were created during verification — user may delete them.

**What's left (all optional, pick up here tomorrow):**
1. **Phase 3 — Advice** (the main next milestone): budget vs actual (`categories.budget_amount`),
   rule-based overspend nudges (`GET /insights` → `insights` table), insights feed on the dashboard.
2. **LLM-assisted categorization** — the rules categorizer returns "Uncategorized" for unknown
   vendors (e.g. "Pingo Doce"/"PD OLAIAS", a grocery store). Easy win: have the LLM suggest a
   category while it's already reading the receipt, or expand the keyword rules.
3. Fix the weekly-detection cron workflow publish (minor n8n version quirk).
4. T15 savings polish (savings already recorded on `refund_actions.saved_amount`).
5. See the plan + the detailed status in the auto-memory file:
   `C:\Users\aimilios\.claude\projects\C--Users-aimilios-Desktop-CV-creation\memory\receipt-ghostbuster-status.md`
   (the single most complete source of current state — read it first).

---

## Original greenfield brief (HISTORICAL — kept for context)

You are picking up a greenfield project. Read this file **and** the implementation plan
before doing anything. Ask the user for the credentials listed below before you start building.

---

## 1. Files to read first
- **Implementation plan (the build steps):**
  `C:\Users\aimilios\.claude\plans\save-it-as-a-expressive-blossom.md`
- **App overview (plain-language reference, already written):**
  `C:\Users\aimilios\Desktop\CV-creation\RECEIPT-GHOSTBUSTER\APP_OVERVIEW.md`
- **Build everything inside:** `C:\Users\aimilios\Desktop\CV-creation\RECEIPT-GHOSTBUSTER\`

## 2. Ignore the rest of the parent folder
The `CV-creation` folder also contains a **different project** and the user's CVs:
`APP_OVERVIEW (1).md`, `tradehub_implementation_plan (1) (1).md`, `CV-AimK-*.html`, `CV-AimK.pdf`,
`photo Aimilios.jpg`. These are **reference/unrelated** — do NOT read them as part of this task,
do NOT edit them, do NOT mix TradeHub content into Receipt Ghostbuster.

---

## 3. What the app is (one paragraph)
A **personal money assistant**. Every expense — a snapped receipt OR a hand-typed cash
entry — gets extracted, categorized, VAT-split, reconciled against the bank (via uploaded
CSV), and rolled into a monthly close. It then hunts dead subscriptions and advises where
to cut. Full details in `APP_OVERVIEW.md`.

**One line:** messy expense in → clean, reconciled, categorized record out — with a human
confirm gate and the weird stuff flagged.

## 4. Why it exists (affects your priorities)
This is a **portfolio project** for the user to land **product-engineer / forward-deployed
/ finance-analyst** roles. It must prove three things: (1) he can **ship**, (2) he can
**automate a messy manual process end-to-end**, (3) he has **real accounting depth**.
→ **Prioritize a clean, fully-working, demoable Phase 1 with a README demo script over
extra features.** A polished small thing beats a half-built big thing.

---

## 5. Locked decisions — do NOT re-litigate
- **Stack:** React + Vite (frontend) · Python/FastAPI (extraction & reconciliation logic) ·
  n8n (orchestration + refund emails) · Supabase (Postgres + auth + storage) ·
  vision LLM for receipt reading · **bank data via CSV import** (no open-banking API).
- **Phasing:** build in **strict order** (Prerequisites → T1 … T18 in the plan).
  **Ship Phase 1 fully working BEFORE starting Phase 2 or 3.** This phased ship is
  intentional and is itself part of the story.
- **Out of scope (do not add):** multi-currency/FX, full double-entry bookkeeping,
  tax-return generation, multi-user/client accounts, live bank API.

## 6. Hard rules
- **Never auto-send** anything financial or any email. Cancel/refund emails are
  **draft-only**; the user approves before anything sends. Human-confirm gate always.
- **Secrets stay server-side** (FastAPI/n8n/Supabase). The frontend NEVER holds API keys.
- **Cash vs bank logic matters:** cash expenses count in totals/categories but are
  **excluded from reconciliation** (nothing in the bank to match them to) — so they must
  not show up as false "unmatched" exceptions. This distinction is deliberate.
- **The AI never does math or is trusted blindly:** confidence gate routes uncertain
  extractions to a review queue; VAT/reconciliation/close totals are computed in code.

## 7. Environment
- **OS:** Windows 10, shell is **PowerShell** (a Bash tool is also available for POSIX scripts).
- Keep the repo structure from the plan: `/backend /frontend /db /n8n /sample-data` + `README.md`.

---

## 8. What to ask the user for BEFORE building (you cannot create these yourself)
- **Supabase** project URL + keys (and confirm the project is created)
- A **vision-LLM API key** (Anthropic or OpenAI)
- **Self-hosted n8n** URL / access — only needed at Phase 2
- **Gmail** connection — only needed at Phase 2
- A few **sample receipt images** + a **sample bank-statement CSV** for testing

## 9. First actions (suggested)
1. Read the plan file end-to-end.
2. Confirm the credentials in §8 with the user.
3. Do Prerequisites P1–P3, then start Phase 1 at T1 (DB schema) and go in order.
4. Stop at the Phase 1 gate, demo it, then continue.
