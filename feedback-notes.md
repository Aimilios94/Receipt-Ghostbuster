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

---

## Round 2 — 2026-10-13 (self-testing, developer) — per-line VAT on a real mixed-rate receipt

**Setup:** local build (backend `:8000` OpenAI gpt-4o, frontend `:5173`), uploaded a real **Continente** receipt (`1000017708.jpg`) with **three VAT rates** on one ticket (printed IVA summary: A 6% → €0.32, B 13% → €0.66, C 23% → €0.02; total €11.58).

**Tester:** Aimilios (developer self-test).

**What was exercised:** receipt upload → review queue → edit → per-rate VAT.

**Observations:**

- **Date misread → "in the future" → review.** The extractor returned `2026-10-26`, which the guardrail correctly flagged as a future date (today 2026-10-13) and routed to review. The receipt's real date is **2026-10-05** (printed `05/10/2026` by the invoice number). The model had picked up the bottom card-terminal line `26-10-05` (YY-MM-DD) and read the `26` as the day. → **FIXED:** the extraction prompt now points at the top `DD/MM/YYYY` invoice date as primary and explicitly says not to read the bottom `YY-MM-DD` terminal line's fields as day/month. (The date was always editable in review as a fallback.)
- **Edit form only allowed ONE VAT rate.** The receipt has 6% + 13% + 23% lines, but review Edit offered a single VAT-rate field — no way to enter a real mixed-rate receipt by hand. → **FIXED:** the Edit form now has a **multi-rate VAT editor** — add one line per rate (description, € gross, rate 6/13/23/0), seeded from the extracted line items; the backend sums VAT **per rate in code** and stores the lines. Amount auto-syncs to the lines' total.
- **Couldn't find the detailed per-rate VAT.** User looked on the dashboard and ledger and couldn't see the breakdown. → **CAUSE:** (a) while a receipt is in review it isn't on the ledger yet; (b) the dashboard is **month-scoped** to the September sample data, so an October receipt only appears on the **Ledger** (all months); (c) the breakdown opens by **clicking** the VAT number. → **FIXED/ADDRESSED:** the per-rate breakdown now shows **live inside the Edit form** as you set the rates; after posting it's on **Ledger → click the "VAT" total** in the footer (and the Dashboard "VAT paid" card for the receipt's month).
- **Bucket rounding bug caught during the fix.** Summing VAT **per line** gave 13% → €0.67 / total €1.01, but the receipt prints €0.66 / €1.00. → **FIXED:** VAT is now computed on each rate's **gross bucket total** (split once per rate), matching the printed Portuguese IVA summary to the cent.

**Candidate decisions (→ [DECISIONS.md](DECISIONS.md)):**
1. **Per-line VAT is manually editable, not just extracted** — the review Edit form is a full multi-rate editor. ✅ built (extends D12).
2. **VAT per rate uses bucket rounding** (VAT on the rate's gross total), matching how receipts print it. ✅ built (D12).
3. **Date reading** prefers the top four-digit invoice date over the bottom terminal short date. ✅ fixed (extends D7).

**Round 2 outcome:** 4 observations, all fixed the same day. Verified end-to-end against live Supabase: the real 3-rate Continente receipt reconciles to **6% €0.32 · 13% €0.66 · 23% €0.02 = €1.00**, gross €11.58 — matching the printed IVA summary exactly. Remaining real-test step: re-upload `1000017708.jpg` through gpt-4o now that the date prompt is fixed, confirm it auto-reads the 3 rates (vs. entering them by hand in review).

---

## Round 3 — 2026-10-15 (self-testing, developer) — extraction robustness on hard real receipts

**Setup:** local build (backend `:8000` OpenAI gpt-4o, frontend `:5173`), live Supabase. A long driving session uploading a **variety of real receipts**, each exposing a different extraction edge case: Continente `1000017808.jpg` (3-rate), Uber Eats `1000017810.jpg` (discount, no VAT), Auchan `1000017811.jpg` (sideways, 2-rate), Continente `1000017779.jpg` (crumpled, 3-rate + discount), a tobacco receipt (`viva.com`, 0% VAT), and others.

**Tester:** Aimilios (developer self-test).

**What was exercised:** receipt upload → categorization → per-rate VAT → date reading → discounts → no-VAT receipts → rotation → review/edit/retake → reconciliation-exception detail.

**Observations & fixes (all shipped same day):**

- **LLM categorization works.** Continente / PD OLAIAS / Pingo Doce came back "Uncategorized" from the rules. → **FIXED:** gpt-4o now suggests a category during extraction; rules run first (fast/auditable), the suggestion fills the gaps, validated against the real category list. These three now land in **Groceries**. Later added a **Tobacco** category for a cigarette receipt.
- **"Stop guessing the VAT."** On a 3-rate Continente the model fabricated per-line amounts/VAT to force the total, getting the rates wrong (e.g. 6% €0.09 instead of €0.15). → **FIXED:** the receipt **prints an exact IVA summary table**; the extractor now **transcribes that table** (`tax_lines`) and it becomes the VAT source of truth when it ties to the total — read, never guess. Reproduced the printed 6% €0.15 · 23% €0.30 to the cent.
- **The amount near the vendor was the line-sum, not what I paid.** → **FIXED:** the edit form's Amount is now the **full amount paid** (editable), with the VAT lines a breakdown and an amber hint when they don't reconcile.
- **Discounts counted wrong.** Uber Eats (Subtotal €32.38 − Special Offer €13.99 = **€18.39 paid**) and Continente POUPANÇA lines confused the read. → **FIXED:** discounts (POUPANÇA / Special Offer / Desconto / parenthesised negatives) are **never products**; `total` is always the amount **paid after** discount; a discounted receipt's lines are scaled to the amount paid so VAT is computed on what was paid.
- **No VAT printed (Uber Eats, tobacco).** I can't know what VAT a pizza/olives/coke carries. → **FIXED:** when a receipt lists products but prints no VAT, gpt-4o **estimates** the standard Portuguese rate per product (prepared food 13%, drinks 23%, groceries 6%); VAT is computed in code, the receipt goes to **review marked "suggested"** (amber VAT fields + tooltip), and you confirm. A genuine **0%** (tobacco) is a captured answer — it no longer shows as "missing VAT" in reconciliation.
- **Dates: year repeatedly misread.** A receipt dated 2026-10-14 read as 2021/2023-10-14, and Auchan's `Data Emissão: 2026-10-13` read as 2021-10-14. → **FIXED (code, not just prompt):** a focused **date re-read** pass + a deterministic **year-repair** that snaps an implausibly-old date to the most recent plausible year (never to a future date) and **forces review** with "year looked misread — corrected X to Y, confirm." Plus prompt handling of the `Data Emissão` ISO date and the `YY-MM-DD` terminal line.
- **Net read as the total.** Auchan stored €3.77 (the printed BASE/net) instead of the €4.18 paid. → **FIXED:** when the model's "total" matches the breakdown's **net** rather than its **gross**, the code stores the **gross (net + VAT)** as the amount paid.
- **Sideways / crumpled receipts misread everything.** → **FIXED (deterministic):** **server-side auto-rotation** (Pillow) — apply EXIF orientation, detect landscape, and re-read at 90°/270°/0° (180° fallback), keeping the orientation that reads most upright/reconciling; the **straightened image is stored**. Confirmed the sideways Auchan then read correctly.
- **A crumpled receipt still auto-posted a confidently-wrong read** (the model even invented items not on the ticket). → **FIXED:** a **self-consistency guardrail** — when the model returns both a printed VAT table and item lines and they **disagree per-rate**, the read is flagged unreliable and **not auto-posted**. Plus a **retake prompt** at upload (and a **Retake** button in the review queue) when a read looks low-quality (reconcile mismatch / misread date / low confidence).
- **UX polish across the board:** Ledger columns are now **Net · VAT · Total** (was Amount · VAT); the Ledger **Category is an editable dropdown** (like Status); reconciliation **exceptions are clickable → full detail** (net/VAT/total, date, receipt) and **deletable**, newest-upload **sorted first** with an unread **"NEW"** highlight; the detail popup reads **Net (total) · VAT (total) · Paid**; per-VAT-line **net · VAT · total** display with **0%** promoted in the rate picker.

**Candidate decisions (→ [DECISIONS.md](DECISIONS.md)):** D14 printed-table VAT source of truth · D15 LLM categorization · D16 date year-repair + re-read · D17 discounts modelled, never products · D18 estimated VAT when none printed · D19 amount paid = net + VAT · D20 server-side auto-rotation · D21 self-consistency guardrail + retake UX.

**Round 3 outcome:** a large batch of extraction-robustness fixes, all shipped and verified against live Supabase; backend tests **53 → 80 passing**. **Honest finding (reinforces D9):** on **flat, well-lit** receipts these fixes make reads auto-post correctly; on a **physically crumpled** receipt, single-pass OCR still produces the occasional confident wrong read — the system now **catches it** (consistency guardrail + retake prompt), **routes it to review**, and lets the user **edit, retake, or delete**. No prompt invents the right digits off creased paper; the reliable remedies are a flatter re-shoot or manual edit. A **read-twice-and-compare** consensus mode was discussed and deferred as a future option.

---

## Round 4 — 2026-10-18 (self-testing, developer) — real bank statement + reconciliation workbench

**Setup:** local build (backend `:8000` OpenAI gpt-4o, frontend `:5173`), live Supabase. Driving session importing a **real Revolut CSV** (`octomber-2026.csv`, 44 rows) and re-reading real receipts, exposing bank-import, reconciliation, and receipt-editing gaps.

**Tester:** Aimilios (developer self-test).

**What was exercised:** bank-statement import (CSV + PDF) → statement grouping → reconciliation (auto + manual) → online-payment handling → receipt re-scan → printed-VAT consistency.

**Observations & fixes (all shipped same day):**

- **"I can't get a CSV every time — accept a PDF too."** → **FIXED:** the Import dialog now accepts a text-based **PDF** as well as a CSV; the backend extracts the text (`pdfplumber`), structures it with gpt-4o (reading only — amounts/dates re-parsed and signed in code), with a deterministic regex fallback. A scanned/image PDF is rejected with a clear message rather than guessed at.
- **CSV import failed with "Can't reach the backend."** The real cause was a non-standard date column (Revolut uses `Completed Date`), which wrote an empty date → a DB 500 that, lacking CORS headers, surfaced as a network error. → **FIXED:** the parser now **auto-detects** column names across EN/PT/ES/DE exports (incl. Revolut `Completed/Started Date`, debit/credit), sniffs the delimiter, strips the time off a `D/M/YYYY HH:MM` date, and **skips not-yet-settled rows** (`PENDING`/`REVERTED`). A blank/garbage date is never stored; errors return proper 400/502 with the real cause.
- **"Top-ups and transfers aren't purchases — they don't need a receipt."** → **FIXED ([D23](DECISIONS.md)):** a bank line is reconcilable only if it's money *out* AND not a top-up / transfer / exchange / ATM (detected from the statement `Type` column or the description). Those are still imported and counted but never flagged "missing a receipt." On the real statement: 20 card purchases need receipts; 8 top-ups + 13 transfers excluded.
- **"After importing, the exceptions list floods with every bank line — I get lost."** → **FIXED ([D24](DECISIONS.md)):** imported files are now first-class **Bank statements** (a new section listing each file, its period, and Spent/Received/Net totals, drilling into every transaction). On the dashboard and Reconciliation the unmatched bank lines **collapse into one row per statement** (NEW-flagged until opened).
- **"Show me the reconciliation result and let me match/unmatch by hand."** → **FIXED:** running reconciliation opens a **results popup** (matched receipt↔bank pairs one by one with View receipt + View transaction, the unmatched expenses, and the bank payments still needing a receipt); a **Match manually** button opens the same view without running the matcher; manual **match / unmatch** persist.
- **"The suggested matches were random."** The first pass suggested the closest-by-amount bank line even on an unrelated vendor (an Uber Eats receipt vs a Continente line). → **FIXED:** suggestions are only offered for a **real reason** — the **same vendor**, or an **exact amount within a few days**; otherwise the row reads "No likely match · stays pending." Added **Not a match** (rejects a suggestion, keeps the expense pending) and a **No receipt** action for online-only payments (takes them out of the reconciliation cycle).
- **"Let me re-upload a better photo of a receipt I already have."** → **FIXED:** next to every **View receipt** there's now an **Edit** action that uploads a new photo, replaces the stored image, and **re-reads** it (amount/VAT/vendor/date/line-items refreshed; if the new photo can't be read, the image is swapped but the figures are kept).
- **"The totals don't match — footer says €37.50 but the total is €48.24."** On a crumpled Pingo Doce, the model misread one digit of the 23% IVA line (13,31→13,11), pushing the printed table 0.20 outside the old 5-cent tolerance → the table was dropped and the figures fell back to item lines that summed to only €37.50. → **FIXED (extends [D14](DECISIONS.md)):** the printed IVA table is now accepted within a **relative** tolerance and its buckets are **scaled to the exact total**, so net + VAT + paid always reconcile (that receipt now reads Net €43.79 · VAT €4.45 · Paid €48.24).
- **Infra:** a heavy reconciliation run overlapping the UI's refetches tripped a transient Windows socket error (`WinError 10035`) on the shared Supabase client, flashing "can't reach the backend." → **FIXED:** the Supabase client is now created **per worker thread**, removing the contention; the frontend also retries transient failures.

**Candidate decisions (→ [DECISIONS.md](DECISIONS.md)):** D22 PDF import · D23 top-ups/transfers aren't purchases · D24 statements first-class + collapsed exceptions · D25 online-payment "no receipt" + manual reconciliation workbench. Printed-table tolerance + scaling extends D14.

**Round 4 outcome:** bank import now handles a real Revolut CSV and PDF statements; reconciliation became a hand-drivable workbench (match / unmatch / not-a-match / no-receipt / re-scan) with believable suggestions only; receipt totals stay internally consistent through a crumpled-digit misread. All verified in-browser against live Supabase; backend tests **80 → 97**. Sample demo data was cleared at the tester's request so the ledger shows only real uploads (reload via `scripts/load_sample_data.py` + `load_phase2_demo.py` before a recruiter demo).
