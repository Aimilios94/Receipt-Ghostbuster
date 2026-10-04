"""Monthly close endpoint (T9)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from ..auth import get_current_user_id
from ..services import close as close_service
from .. import repository as repo

router = APIRouter(tags=["close"])


@router.get("/close")
def monthly_close(
    month: str = Query(default=None, description="YYYY-MM; defaults to current month"),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    month = month or date.today().strftime("%Y-%m")
    expenses = repo.list_expenses(user_id)
    bank_txns = repo.list_bank_transactions(user_id)
    return close_service.monthly_close(expenses, month, bank_txns)


@router.get("/categories")
def categories(user_id: str = Depends(get_current_user_id)) -> dict:
    return {"categories": repo.list_categories(user_id)}
