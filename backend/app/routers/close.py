"""Monthly close endpoint (T9)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user_id
from ..models import CategoryBudgetUpdate
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


@router.post("/categories/{category_id}/budget")
def set_category_budget(
    category_id: str,
    body: CategoryBudgetUpdate,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Set (or clear, with null) a category's monthly budget — drives the
    budget-vs-actual view and the over_budget nudge (v0.4)."""
    row = repo.update_category(user_id, category_id, {"budget_amount": body.budget_amount})
    if not row:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"category": row}
