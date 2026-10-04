"""Reconciliation: match expenses to bank transactions.

Pure logic over plain dicts so it is fully unit-testable. Rules:
  - CASH expenses are skipped entirely (nothing in the bank to match) — by design
    they are NOT unmatched exceptions.
  - A candidate match requires: amount within `amount_tolerance`, txn_date within
    `date_window_days` of expense_date, and fuzzy vendor score >= `vendor_min_score`.
  - Matching is greedy/one-to-one: each bank txn is used at most once. We rank
    candidates by (vendor score desc, date distance asc, amount distance asc) and
    assign best-first so the strongest pairs win.
Bank amounts are signed (negative = money out); we compare on absolute value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from rapidfuzz import fuzz


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def vendor_score(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return float(fuzz.token_set_ratio(a.lower(), b.lower()))


@dataclass
class ReconcileResult:
    matches: list[dict[str, Any]] = field(default_factory=list)   # {expense_id, transaction_id, ...}
    matched_expense_ids: set = field(default_factory=set)
    matched_transaction_ids: set = field(default_factory=set)


def reconcile(
    expenses: list[dict[str, Any]],
    bank_txns: list[dict[str, Any]],
    *,
    amount_tolerance: float = 0.01,
    date_window_days: int = 3,
    vendor_min_score: int = 70,
) -> ReconcileResult:
    """Return best one-to-one matches between non-cash expenses and bank txns."""
    candidates: list[dict[str, Any]] = []

    for exp in expenses:
        if exp.get("source") == "cash":
            continue
        if exp.get("reconciled"):
            continue
        exp_amount = abs(float(exp["amount"]))
        exp_date = _as_date(exp["expense_date"])
        for txn in bank_txns:
            if txn.get("matched_expense_id"):
                continue
            amount_diff = abs(abs(float(txn["amount"])) - exp_amount)
            if amount_diff > amount_tolerance:
                continue
            day_diff = abs((_as_date(txn["txn_date"]) - exp_date).days)
            if day_diff > date_window_days:
                continue
            score = vendor_score(exp.get("vendor"), txn.get("description"))
            # Vendor text on bank lines is noisy; allow a match on a tight
            # amount+date even when vendor text is weak, but prefer strong vendor.
            if score < vendor_min_score and not (amount_diff <= amount_tolerance and day_diff == 0):
                continue
            candidates.append(
                {
                    "expense_id": exp["id"],
                    "transaction_id": txn["id"],
                    "vendor_score": score,
                    "day_diff": day_diff,
                    "amount_diff": amount_diff,
                }
            )

    # Best-first: strongest vendor match, then closest date, then closest amount.
    candidates.sort(key=lambda c: (-c["vendor_score"], c["day_diff"], c["amount_diff"]))

    result = ReconcileResult()
    for c in candidates:
        if c["expense_id"] in result.matched_expense_ids:
            continue
        if c["transaction_id"] in result.matched_transaction_ids:
            continue
        result.matched_expense_ids.add(c["expense_id"])
        result.matched_transaction_ids.add(c["transaction_id"])
        result.matches.append(c)

    return result


def find_amount_discrepancies(
    expenses: list[dict[str, Any]],
    bank_txns: list[dict[str, Any]],
    *,
    amount_tolerance: float = 0.01,
    date_window_days: int = 3,
    vendor_min_score: int = 85,
) -> list[dict[str, Any]]:
    """Find likely-same transactions whose AMOUNTS disagree beyond tolerance.

    A strong vendor match (higher bar than reconciliation) + a close date, but an
    amount difference, is the classic 'receipt says X, bank charged Y' discrepancy
    (a tip, a price change, an FX rounding). These are surfaced for review rather
    than auto-matched. Only considers still-open expenses and bank txns.
    """
    out: list[dict[str, Any]] = []
    used_txn_ids: set = set()
    for exp in expenses:
        if exp.get("source") == "cash" or exp.get("reconciled"):
            continue
        exp_amount = abs(float(exp["amount"]))
        exp_date = _as_date(exp["expense_date"])
        best = None
        for txn in bank_txns:
            if txn.get("matched_expense_id") or txn["id"] in used_txn_ids:
                continue
            score = vendor_score(exp.get("vendor"), txn.get("description"))
            if score < vendor_min_score:
                continue
            day_diff = abs((_as_date(txn["txn_date"]) - exp_date).days)
            if day_diff > date_window_days:
                continue
            amount_diff = round(abs(abs(float(txn["amount"])) - exp_amount), 2)
            if amount_diff <= amount_tolerance:
                continue  # within tolerance -> reconcile() would have matched it
            cand = {
                "expense": exp,
                "transaction": txn,
                "difference": amount_diff,
                "vendor_score": score,
            }
            if best is None or amount_diff < best["difference"]:
                best = cand
        if best is not None:
            out.append(best)
            used_txn_ids.add(best["transaction"]["id"])
    return out
