# Sample data

A small, self-contained dataset for the Phase 1 demo. It is deliberately shaped so
every reconciliation path shows up.

## Files
- `bank_september_2026.csv` — 14 bank lines for September 2026 (signed amounts;
  negative = money out). Includes salary (income), regular spend, and recurring
  subscription charges (Netflix/Spotify) that will become Phase 2 candidates.
- `sample_expenses.json` — expenses to POST to `/expenses` (card + cash).
- Drop your own receipt photos here (e.g. `receipt_*.jpg`) to demo `/extract`.

## The story this data tells
| Scenario | How it shows up |
|---|---|
| **Clean matches** | Lidl, Starbucks, Shell, AB Vasilopoulos, Aegean, Pharmacy, Public → matched to their bank lines by amount + date + fuzzy vendor |
| **Amount mismatch** | Adobe receipt = €24.00 but bank charged €24.99 → `/exceptions` amount_mismatch |
| **Duplicate** | Lidl €43.20 on 2026-09-02 entered twice → `/exceptions` duplicates |
| **Unmatched bank** | Netflix, Spotify, Cosmote, Uber have no logged expense → `/exceptions` unmatched_bank (Phase 2 subscription hunt) |
| **Cash excluded** | Corner Bakery €3.50, Farmers Market €25.00 → counted in totals/categories but **never** flagged as unmatched |
| **Income** | Salary €2500 → counted as money in, excluded from spend-by-category |

## Load it
With the backend running and the schema applied:
```
cd backend
python scripts/load_sample_data.py
```
This posts the expenses, imports the CSV, runs reconciliation, and prints the
exceptions summary and the September monthly close.
