# Receipt Ghostbuster — Handoff Notes (read this first)

> ⚠️ **The sections below under "Original greenfield brief" are HISTORICAL** (from before
> any code existed). For the current state, read **"RESUME HERE" first.** The project is
> no longer greenfield — Phase 1 and Phase 2 are built, working, and on GitHub.

---

## 🟢 RESUME HERE — current status (as of 2026-10-04, end of day)

**Where we are:** Phase 1 (Track & Reconcile) and Phase 2 (Refund Hunter) are **both complete,
working end-to-end, and pushed to GitHub.** The app is a real, demoable product.

**GitHub:** https://github.com/Aimilios94/Receipt-Ghostbuster (branch `main`, all work pushed;
`git status` clean). Latest commit `6c675a1`.

**What's built & verified:**
- **Phase 1 — backend:** FastAPI. Receipt extraction (vision LLM) + confidence gate, rules
  categorization, VAT math, bank CSV import, reconciliation engine, month-scoped exceptions,
  monthly close. **40-ish pytest tests pass** (`cd backend && ./.venv/Scripts/python.exe -m pytest -q`).
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
- **Anthropic API is OUT OF CREDITS** → email drafts fall back to the deterministic template
  (works fine) and live receipt `/extract` will fail until topped up. Not a code bug.
- **n8n container** is currently running with `-e N8N_LOG_LEVEL=debug` (turned on to debug Gmail).
  Fine to leave; recreate without it for quieter logs (volume persists the active workflow + creds).
- The **weekly-detection cron** workflow (`/n8n/detect-subscriptions-cron.json`) is imported but
  **won't publish** due to an n8n 2.x version/publish quirk — low priority, the manual "Run
  detection" button works. If needed: edit it in the UI, make a tiny change, Save, then Publish.
- A few **test Gmail drafts** were created during verification — user may delete them.

**What's left (all optional, pick up here tomorrow):**
1. Fix the weekly-detection cron workflow publish (minor).
2. T15 savings polish (savings already recorded on `refund_actions.saved_amount`).
3. **Phase 3 — Advice:** budget vs actual (`categories.budget_amount`), rule-based overspend
   nudges (`GET /insights` → `insights` table), insights feed on the dashboard. See the plan +
   the detailed status in the auto-memory file:
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
