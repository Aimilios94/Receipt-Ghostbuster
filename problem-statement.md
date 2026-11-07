# Problem Statement

*Written once, before building. This is the "why" the rest of the project is measured against. Only the status table under the success criteria is kept current.*

## Who it's for

One person managing their own money — specifically someone who:

- pays for things across **cash and card**, so no single statement tells the whole story,
- deals with **VAT** (a freelancer, sole trader, or anyone who wants to know how much tax they actually paid),
- has a handful of **recurring subscriptions** they've half-forgotten about,
- and has never once run a proper **month-end** on their own finances.

It is deliberately **single-user**. Not a team tool, not a client-accounting product.

## The problem

People don't actually know where their money goes. In practice:

- **Receipts get lost.** The paper fades or gets thrown away, so the detail (what, where, how much VAT) is gone.
- **Cash spend is invisible.** It never appears on a bank statement, so any "where did my money go" view built only on the bank is wrong.
- **Subscriptions renew silently.** A €10/month service you stopped using is €120/year leaving quietly.
- **No one runs a real month-end on their own life.** A bank balance is not a reconciliation. Nobody checks that what they *think* they spent matches what the *bank* says, or flags the mismatches.

Doing this by hand is tedious and error-prone, so it doesn't get done.

## What it solves

Receipt Ghostbuster automates the messy manual process end-to-end:

> **messy expense in → clean, reconciled, categorized record out — with a human confirm gate and the weird stuff flagged.**

- Snap a receipt **or** type a cash expense.
- A vision model extracts vendor / amount / date / VAT; uncertain reads go to a **review queue** instead of being trusted blindly.
- Card spend is **reconciled against the bank statement**; mismatches surface as **exceptions** (unmatched, duplicate, amount-differs, missing VAT).
- Cash is counted in totals but **excluded from reconciliation** — there's nothing in the bank to match it to.
- A **monthly close** summarizes the numbers: money in/out, VAT paid, what's still unreconciled.
- Later phases hunt dead subscriptions and advise where to cut.

## What "good" looks like (success criteria)

- Adding an expense — snap or cash — takes **seconds**, not minutes.
- The **AI never does the money math and is never trusted blindly**: all VAT / reconciliation / close totals are computed in code; low-confidence extractions are reviewed by a human.
- A month-end that would take **~1–2 hours by hand** is produced in **minutes**.
- Every number on every screen traces back to **one ledger** — no double-entry, no disagreeing totals.
- Nothing financial is ever sent or charged automatically; the human approves.

### Status against those criteria (checked 2026-11-07)

| Criterion | State | Evidence |
|---|---|---|
| Adding an expense takes seconds | **Not met** for a snapped receipt; manual entry `NO_DATA` (not timed) | A `gpt-5-mini` read takes 23.9s at p50 and 79.1s at p95 (n=26, 2026-11-06, [MODELS.md](backend/eval/MODELS.md)). Accuracy was chosen over speed ([D27](DECISIONS.md)). |
| The AI never does the money math and is never trusted blindly | Built and tested | [D1](DECISIONS.md), [D40](DECISIONS.md); the numbers are unit-tested, and the gate is measured ([D30](DECISIONS.md)). |
| A month-end takes minutes, not ~1–2 hours | `NO_DATA` | No month-end has been timed, and the 1–2 hours is an estimate. A close is also a summary today: it isn't saved or locked. |
| Every number traces back to one ledger | Built | [D10](DECISIONS.md) |
| Nothing financial is sent or charged automatically | Built | [D4](DECISIONS.md) |

## Explicitly out of scope

Multi-currency / FX · full double-entry bookkeeping · tax-return generation · multi-user / client accounts · live open-banking API. These would delay shipping without strengthening the core promise.

---

*The engineering process (roadmap → decisions → changelog, driven by real testing feedback) is tracked in the linked docs from the [README](README.md).*
