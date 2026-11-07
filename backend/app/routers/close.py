"""Monthly close endpoint (T9)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user_id
from ..models import CategoryBudgetUpdate
from ..config import Settings, get_settings
from ..services import close as close_service, close_record, exceptions as exc
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
    out = close_service.monthly_close(expenses, month, bank_txns)
    saved = repo.get_monthly_close(user_id, month)
    out["saved_close"] = saved
    out["changed_since_close"] = close_record.changes(saved["summary"], out) if saved else []
    return out


def _exception_counts(user_id: str, month: str, settings: Settings) -> dict:
    expenses = [
        e for e in repo.list_expenses(user_id)
        if str(e["expense_date"])[:7] == month and e.get("status") != "pending_review"
    ]
    bank = [t for t in repo.list_bank_transactions(user_id) if str(t["txn_date"])[:7] == month]
    found = exc.collect(expenses, bank, amount_tolerance=settings.reconcile_amount_tolerance,
                        date_window_days=settings.reconcile_date_window_days)
    return {k: len(v) for k, v in found.items()}


@router.post("/close/{month}/save")
def save_close(
    month: str,
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Record the month as closed, with its figures. Only a month with nothing left to
    reconcile can be closed. Closing again replaces the record."""
    if len(month) != 7 or month[4] != "-":
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    current = close_service.monthly_close(repo.list_expenses(user_id), month, repo.list_bank_transactions(user_id))
    if current["unreconciled_count"]:
        raise HTTPException(status_code=400, detail="Reconcile every card expense before closing the month.")
    snap = close_record.summary(current, _exception_counts(user_id, month, settings))
    saved = repo.save_monthly_close(user_id, month, snap, datetime.now(timezone.utc).isoformat())
    return {"saved_close": saved}


@router.delete("/close/{month}/save")
def reopen_close(month: str, user_id: str = Depends(get_current_user_id)) -> dict:
    """Reopen a closed month: its close record is removed. Nothing else changes."""
    return {"reopened": repo.delete_monthly_close(user_id, month)}


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
