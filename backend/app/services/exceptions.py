"""Exception detection — the 'weird stuff' surfaced for human review.

All pure functions over dicts. Categories:
  - unmatched_expenses: non-cash, not reconciled (cash is excluded by design).
  - unmatched_bank: bank txns with no matched expense.
  - duplicates: expenses sharing the same (vendor, amount, expense_date).
  - amount_mismatch: reconciled pairs whose amounts differ beyond tolerance
    (shouldn't happen via reconcile(), but catches manual/edited links).
  - missing_vat: receipt-sourced expenses with no VAT captured.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import reconciliation


def unmatched_expenses(
    expenses: list[dict[str, Any]], exclude_ids: set | None = None
) -> list[dict[str, Any]]:
    exclude_ids = exclude_ids or set()
    return [
        e
        for e in expenses
        if e.get("source") != "cash"
        and not e.get("reconciled")
        and e.get("id") not in exclude_ids
    ]


def unmatched_bank(
    bank_txns: list[dict[str, Any]], exclude_ids: set | None = None
) -> list[dict[str, Any]]:
    exclude_ids = exclude_ids or set()
    return [
        t
        for t in bank_txns
        if not t.get("matched_expense_id") and t.get("id") not in exclude_ids
    ]


def duplicates(expenses: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for e in expenses:
        key = (
            (e.get("vendor") or "").strip().lower(),
            round(float(e["amount"]), 2),
            str(e.get("expense_date"))[:10],
        )
        groups[key].append(e)
    return [grp for grp in groups.values() if len(grp) > 1]


def amount_mismatch(
    expenses: list[dict[str, Any]],
    bank_txns: list[dict[str, Any]],
    *,
    amount_tolerance: float = 0.01,
) -> list[dict[str, Any]]:
    by_id = {t["id"]: t for t in bank_txns}
    out = []
    for e in expenses:
        tid = e.get("matched_transaction_id")
        if not tid or tid not in by_id:
            continue
        diff = abs(abs(float(by_id[tid]["amount"])) - abs(float(e["amount"])))
        if diff > amount_tolerance:
            out.append({"expense": e, "transaction": by_id[tid], "difference": round(diff, 2)})
    return out


def missing_vat(expenses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Receipt-sourced expenses whose VAT was never captured at all.

    An EXPLICIT 0% (zero-rated / exempt — e.g. tobacco, stamps) is a captured answer,
    not a gap: `vat_rate` or `vat_amount` is set to 0. We only flag the truly-unknown
    case where BOTH are None, so confirming a receipt as 0% clears this exception.
    """
    return [
        e
        for e in expenses
        if e.get("input_method") == "receipt"
        and e.get("vat_amount") is None
        and e.get("vat_rate") is None
    ]


def collect(
    expenses: list[dict[str, Any]],
    bank_txns: list[dict[str, Any]],
    *,
    amount_tolerance: float = 0.01,
    date_window_days: int = 3,
    vendor_min_score: int = 85,
) -> dict[str, Any]:
    # Near-match discrepancies (same vendor + date, amount differs). These take
    # precedence so an item shows in exactly one bucket, not also as "unmatched".
    discrepancies = reconciliation.find_amount_discrepancies(
        expenses,
        bank_txns,
        amount_tolerance=amount_tolerance,
        date_window_days=date_window_days,
        vendor_min_score=vendor_min_score,
    )
    # Also include any already-linked pairs whose amounts drifted apart.
    linked = amount_mismatch(expenses, bank_txns, amount_tolerance=amount_tolerance)
    all_mismatch = discrepancies + linked

    disc_exp_ids = {d["expense"]["id"] for d in all_mismatch}
    disc_txn_ids = {d["transaction"]["id"] for d in all_mismatch}

    return {
        "unmatched_expenses": unmatched_expenses(expenses, exclude_ids=disc_exp_ids),
        "unmatched_bank": unmatched_bank(bank_txns, exclude_ids=disc_txn_ids),
        "duplicates": duplicates(expenses),
        "amount_mismatch": all_mismatch,
        "missing_vat": missing_vat(expenses),
    }
