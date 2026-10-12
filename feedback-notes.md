# Feedback Notes

*Real observations from testing rounds. One section per round. This is the **Evidence** source for [DECISIONS.md](DECISIONS.md) — every decision there should trace back to something recorded here. No invented feedback.*

---

## Round 1 — 2026-10-12 (self-testing, developer)

**Setup:** local build, backend `:8000` + frontend `:5173` + n8n `:5678`, OpenAI gpt-4o as the vision provider, September-2026 sample dataset + Phase-2 recurring history loaded.

**Tester(s):** Aimilios (developer self-test).

**What was exercised:** receipt upload, dashboard stat cards, spending-by-category, reconciliation view.

**Observations:**

<!-- Each observation: what I did → what happened → is it a problem? -->

- **Receipt upload works** — uploaded a receipt, it processed and updated normally. ✅
- **Dashboard numbers are dead-ends (main theme).** Every summary figure is read-only; I want each to be a **clickable drill-down** to the underlying expenses. Specifically:
  - **Total spend** card (e.g. "€53.62 · 3 expenses · 2 paid in cash") → click → list the expenses behind it, show *where* each happened, and let me **open the receipt** for a given expense.
  - **VAT paid** card → click → show where the VAT comes from (e.g. Groceries → Pingo Doce), split by **card vs cash**.
  - **Card vs cash** → click → list **both cash and card** payments with **amount + place name** (e.g. Continente).
  - **Reconciled** card → click → show *which* expenses reconciled against the bank statement and **how many are left** to reconcile.
  - **Spending by category** rows (e.g. Groceries, Uncategorized) → click → show detail (amount + where) for both categorized **and** uncategorized items.
- **Duplicate receipts not caught at upload.** When I upload a receipt that duplicates an existing expense, it should **flag it as duplicate/identical at upload time** and give me the option to **double-check** before it posts (current duplicate logic only runs in reconciliation exceptions, not on upload).

- **Dates misread on Portuguese receipts.** The extractor kept reading day-first printed dates (DD/MM/YYYY, standard in Portugal) with the wrong convention — e.g. a receipt actually dated 2026-10-03 came back as the wrong day/year. → **FIXED:** extraction prompt now tells the model these are European/Portuguese day-first dates and to output ISO. Re-upload confirmed it now reads **2026-10-03** correctly.
- **Posting a reviewed receipt didn't update anything.** A receipt flagged to review (e.g. for a date) — once I pressed **Post** to approve it — did not change Total spent, VAT paid, or the reconciliation exceptions. → **ROOT CAUSE:** the close + exceptions + reconcile logic counted `pending_review` receipts *already*, so approving changed only the status, not the numbers (and contradicted the UI's "nothing posts until you confirm"). → **FIXED:** aggregations now count confirmed rows only. Verified: while pending total stayed €63.62 / 4 expenses; after Post it jumped to €111.86 / 5 and the exception count went 3 → 4.

**Candidate decisions (→ [DECISIONS.md](DECISIONS.md)):**
1. **Make dashboard numbers traceable** — every stat card and category row drills down to the source expenses, with receipt view. ✅ built. (Theme: "one ledger, every number traces back to it" — now reachable in the UI.)
2. **Duplicate detection at receipt upload** — flag likely duplicates before posting, with a human double-check (consistent with the existing human-confirm-gate principle). ⬜ pending.
3. **Portuguese date convention** — day-first interpretation in extraction. ✅ fixed.
4. **Only confirmed expenses hit the ledger** — review-queue items are excluded from close/exceptions/reconcile until posted; posting is what puts them on the ledger. ✅ fixed.

- **Rotated / crumpled receipt = unreliable extraction.** A Continente receipt photographed sideways (90°), crumpled, on a dark low-contrast background (`1000017785.jpg`) → gpt-4o misread the date (2023 instead of 2026-10-09), the total (€1.49/€6.08 instead of €4.48), and missed/hallucinated line items — even after adding rotation + "extract every line item" prompt guidance AND `detail:"high"`. → **Finding:** no prompt change reliably fixes a badly-shot image; the right behavior is what already happens — guardrails flag it and route to review (AI never trusted). The same receipt shot flat/upright (Pingo Doce `1000017700.jpg`) extracts perfectly. → **Actions:** keep the prompt/detail improvements; add an in-app capture hint (shoot flat, upright, good light); measure accuracy on normal-quality photos.
- **Need to delete an expense from the dashboard.** After posting, no way to remove a bad row (e.g. the €1.49 Continente that should be €4.48) without leaving the dashboard. → **FIXED:** every expense now has a Delete button in the drill-down lists and the dashboard Ledger preview (with confirm).

5. **Receipt photo quality drives extraction quality** — flag + guide users to shoot flat/upright; guardrails already catch bad reads. ✅ capture hint added to the snap form.
6. **Delete expense from dashboard** — per-row delete in drill-downs + ledger preview. ✅ fixed.

- **"Receipt from the future" false error.** An upright, clear Continente receipt (`1000017784.jpg`, real date 2026-10-06) was flagged as future-dated. → **CAUSE:** the *old* extraction prompt misread the date digits into a future date; the guardrail (correctly) flagged a future date. → **FIXED by the earlier date work:** re-uploaded, it now reads 2026-10-06, total €4.14, both items, and **auto-posts** with no issues.
- **Want to view the receipt while editing + set VAT rate in review.** → **FIXED:** the review Edit form now has a **View receipt** button (opens the image) and a **VAT rate (%)** field (free value with 6/13/23 suggestions; backend recomputes the VAT amount from amount + rate).
- **Want VAT broken down by rate.** → **FIXED:** the VAT drill-down (dashboard VAT card) and a new clickable **VAT total in the Ledger footer** both show VAT grouped by rate (e.g. 23% €3.71 · 13% €0.31 · 6% €0.06). Note: each expense stores ONE rate, so a mixed-rate receipt keeps its dominant rate — a known simplification (full per-line VAT would need a line-item table).

7. **Edit-while-review ergonomics** — view receipt + VAT-rate field in the edit form. ✅ fixed.
8. **VAT by rate** — per-rate breakdown in the VAT drill-down + clickable Ledger VAT total. ✅ fixed.

- **Hard to find/compare flagged duplicates.** A possible duplicate flagged in reconciliation exceptions → pressing Resolve dropped me in the Ledger, but the two duplicate rows were hard to locate and compare. → **FIXED:** the duplicates Resolve link now opens `Ledger?view=duplicates`, which auto-filters to just the duplicate groups; every duplicate row shows a **"Possible duplicate"** amber badge + row highlight, with a delete button, so the pair sits side by side. A "Possible duplicates" filter chip is also always available.

9. **Surface duplicates in the ledger** — badge + highlight + filter + deep-link from the exception. ✅ fixed.

**Carried into [DECISIONS.md](DECISIONS.md):** D6 (guardrails), D7 (Portuguese dates), D8 (confirmed-only ledger), D9 (photo quality + capture hint), D10 (dashboard traceability), D11 (duplicate surfacing). Planned from this round: per-line VAT, duplicate-at-upload, LLM categorization.

**Round 1 outcome:** 9 observations, all actioned the same day — 7 fixed/shipped, 3 logged as planned. Receipt extraction verified working on upright photos (Pingo Doce, Continente); fails safe (routes to review) on a rotated/crumpled photo. The feedback→decision→fix loop ran end-to-end.
