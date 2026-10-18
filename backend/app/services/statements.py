"""Bank-statement aggregation helpers (pure functions over normalized rows)."""
from __future__ import annotations

from typing import Any

from . import reconciliation


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
