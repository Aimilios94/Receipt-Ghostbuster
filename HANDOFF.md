# Receipt Ghostbuster — Handoff Notes (read this first)

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
