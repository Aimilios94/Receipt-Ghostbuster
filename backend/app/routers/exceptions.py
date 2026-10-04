"""Exceptions endpoint (T8): the flagged 'weird stuff'."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..services import exceptions as exc
from .. import repository as repo

router = APIRouter(tags=["exceptions"])


@router.get("/exceptions")
def get_exceptions(
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    expenses = repo.list_expenses(user_id)
    bank_txns = repo.list_bank_transactions(user_id)
    found = exc.collect(
        expenses,
        bank_txns,
        amount_tolerance=settings.reconcile_amount_tolerance,
        date_window_days=settings.reconcile_date_window_days,
    )
    return {
        "counts": {k: len(v) for k, v in found.items()},
        "exceptions": found,
    }
