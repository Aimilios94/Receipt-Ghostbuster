"""Bank-statement aggregation helpers (pure functions over normalized rows)."""
from __future__ import annotations

from collections import Counter
from typing import Any

from . import reconciliation


def _txn_fingerprint(txn: dict[str, Any]) -> tuple:
    """A stable identity for a normalized bank row, used to recognise a transaction
    already imported from an earlier (overlapping) statement.

    `txn_date` is day-granular (csv_import drops the time), so date+amount+description
    alone would wrongly merge legitimately-distinct same-day repeats (e.g. three equal
    top-ups on one day). The running `balance` disambiguates them when present, and a
    count-aware reconciliation in `filter_new_transactions` covers formats with no
    balance column — so neither a true duplicate nor a real repeat is mishandled.
    """
    try:
        amount = round(float(txn.get("amount") or 0), 2)
    except (TypeError, ValueError):
        amount = txn.get("amount")
    desc = (str(txn.get("description") or "").strip().lower()) or None
    bal = txn.get("balance")
    try:
        bal = round(float(bal), 2) if bal is not None else None
    except (TypeError, ValueError):
        bal = None
    return (str(txn.get("txn_date") or "")[:10], amount, desc, bal)


def filter_new_transactions(
    new_rows: list[dict[str, Any]], existing_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Idempotent re-upload: return only the transactions not already stored.

    Count-aware — if a fingerprint is already stored N times, the first N incoming
    rows with that fingerprint are treated as already-present and the rest are new.
    This keeps re-uploading an overlapping statement from duplicating rows (and so
    preserves existing reconciliation) without collapsing genuine same-day repeats.
    """
    remaining: Counter = Counter(_txn_fingerprint(t) for t in existing_rows)
    to_insert: list[dict[str, Any]] = []
    for row in new_rows:
        fp = _txn_fingerprint(row)
        if remaining.get(fp, 0) > 0:
            remaining[fp] -= 1  # matches an already-stored row — skip
            continue
        to_insert.append(row)
    return to_insert, len(new_rows) - len(to_insert)


def statement_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Period + money in/out/net for a set of normalized transaction rows.
    `txn_date` values are ISO strings, so min/max compare correctly."""
    dates = [r["txn_date"] for r in rows if r.get("txn_date")]
    total_in = sum(float(r["amount"]) for r in rows if float(r.get("amount") or 0) > 0)
    total_out = sum(-float(r["amount"]) for r in rows if float(r.get("amount") or 0) < 0)
    net = sum(float(r.get("amount") or 0) for r in rows)
    return {
        "period_start": min(dates) if dates else None,
        "period_end": max(dates) if dates else None,
        "txn_count": len(rows),
        "total_in": round(total_in, 2),
        "total_out": round(total_out, 2),
        "net_amount": round(net, 2),
    }


def needs_receipt(txn: dict[str, Any]) -> bool:
    """A purchase on the statement with no matched expense/receipt yet, that the
    user hasn't acknowledged as a no-receipt (online) payment."""
    return (
        reconciliation.is_reconcilable(txn)
        and not txn.get("matched_expense_id")
        and not txn.get("no_receipt")
    )


def annotate_transaction(txn: dict[str, Any]) -> dict[str, Any]:
    """Tag a transaction with its reconciliation status for the detail view."""
    reconcilable = reconciliation.is_reconcilable(txn)
    return {
        **txn,
        "reconcilable": reconcilable,
        "no_receipt": bool(txn.get("no_receipt")),
        "needs_receipt": needs_receipt(txn),
        "matched": bool(txn.get("matched_expense_id")),
    }
