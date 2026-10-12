"""Exceptions endpoint (T8): the flagged 'weird stuff'.

Scoped to a single month so the view reflects the statement period you are
reconciling — importing older bank history for Refund Hunter does not flood the
current month's exceptions. Defaults to the latest month that has expenses.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..services import exceptions as exc
from .. import repository as repo

router = APIRouter(tags=["exceptions"])


def _month(value) -> str:
    return str(value)[:10][:7]


@router.get("/exceptions")
def get_exceptions(
    month: str = Query(default=None, description="YYYY-MM; defaults to latest month with expenses"),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    expenses = repo.list_expenses(user_id)
    bank_txns = repo.list_bank_transactions(user_id)

    if not month:
        exp_months = sorted({_month(e["expense_date"]) for e in expenses})
        month = exp_months[-1] if exp_months else date.today().strftime("%Y-%m")

    # Exclude receipts still in review — a pending_review expense is not on the
    # ledger yet, so it shouldn't surface as an exception until the user posts it.
    expenses = [
        e
        for e in expenses
        if _month(e["expense_date"]) == month and e.get("status") != "pending_review"
    ]
    bank_txns = [t for t in bank_txns if _month(t["txn_date"]) == month]

    found = exc.collect(
        expenses,
        bank_txns,
        amount_tolerance=settings.reconcile_amount_tolerance,
        date_window_days=settings.reconcile_date_window_days,
    )
    return {
        "month": month,
        "counts": {k: len(v) for k, v in found.items()},
        "exceptions": found,
    }
