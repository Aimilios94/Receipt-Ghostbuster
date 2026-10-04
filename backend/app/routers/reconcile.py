"""Reconciliation endpoint (T7). Matches non-cash expenses to bank txns and
persists the links. Cash is skipped by design."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..services import reconciliation
from .. import repository as repo

router = APIRouter(prefix="/reconcile", tags=["reconcile"])


@router.post("")
def run_reconcile(
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    expenses = repo.list_expenses(user_id)
    bank_txns = repo.list_bank_transactions(user_id)

    result = reconciliation.reconcile(
        expenses,
        bank_txns,
        amount_tolerance=settings.reconcile_amount_tolerance,
        date_window_days=settings.reconcile_date_window_days,
        vendor_min_score=settings.reconcile_vendor_min_score,
    )

    # Persist links both directions.
    for m in result.matches:
        repo.update_expense(
            user_id,
            m["expense_id"],
            {"reconciled": True, "matched_transaction_id": m["transaction_id"]},
        )
        repo.update_bank_transaction(
            user_id, m["transaction_id"], {"matched_expense_id": m["expense_id"]}
        )

    non_cash = [e for e in expenses if e.get("source") != "cash"]
    return {
        "matched": len(result.matches),
        "matches": result.matches,
        "unmatched_expenses": len(non_cash) - len(result.matched_expense_ids),
        "unmatched_bank": len(bank_txns) - len(result.matched_transaction_ids),
        "cash_skipped": len([e for e in expenses if e.get("source") == "cash"]),
    }
