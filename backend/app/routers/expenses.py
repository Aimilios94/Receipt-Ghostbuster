"""Expense endpoints: manual/cash entry (T3), listing, and the review queue (T5)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..models import ExpenseCreate
from ..services import categorization, vat
from .. import repository as repo

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.post("")
def create_expense(
    body: ExpenseCreate,
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Create a manual/cash expense. Cash rows are flagged to skip reconciliation."""
    valid = {c["name"] for c in repo.list_categories(user_id)}
    category = body.category or categorization.categorize(
        body.vendor, body.note, valid_categories=valid or None
    )

    vat_info = vat.resolve_vat(body.amount, body.vat_rate, body.vat_amount)

    row = {
        "source": body.source,
        "input_method": "manual",
        "vendor": body.vendor,
        "amount": body.amount,
        "currency": body.currency or settings.default_currency,
        "expense_date": (body.expense_date or date.today()).isoformat(),
        "category": category,
        "vat_amount": vat_info["vat_amount"],
        "vat_rate": vat_info["vat_rate"],
        "note": body.note,
        "confidence": None,           # manual entries are trusted; no AI confidence
        "status": "posted",
        "reconciled": False,
    }
    created = repo.insert_expense(user_id, row)
    return {"expense": created}


@router.get("")
def list_expenses(
    status: str | None = None,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    return {"expenses": repo.list_expenses(user_id, status=status)}


@router.get("/review-queue")
def review_queue(user_id: str = Depends(get_current_user_id)) -> dict:
    """Low-confidence extractions awaiting human confirmation."""
    return {"expenses": repo.list_expenses(user_id, status="pending_review")}


@router.post("/{expense_id}/confirm")
def confirm_expense(
    expense_id: str,
    body: ExpenseCreate | None = None,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Confirm (and optionally edit) a pending_review expense -> posted."""
    patch: dict = {"status": "posted"}
    if body is not None:
        if body.amount:
            patch["amount"] = body.amount
        if body.category:
            patch["category"] = body.category
        if body.vendor:
            patch["vendor"] = body.vendor
        if body.note is not None:
            patch["note"] = body.note
        if body.expense_date:
            patch["expense_date"] = body.expense_date.isoformat()
        if body.vat_rate is not None or body.vat_amount is not None:
            amount = body.amount or patch.get("amount")
            if amount:
                vat_info = vat.resolve_vat(amount, body.vat_rate, body.vat_amount)
                patch["vat_amount"] = vat_info["vat_amount"]
                patch["vat_rate"] = vat_info["vat_rate"]
    updated = repo.update_expense(user_id, expense_id, patch)
    return {"expense": updated}


@router.delete("/{expense_id}")
def delete_expense(
    expense_id: str,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Permanently remove an expense (e.g. discarding a bad receipt read)."""
    ok = repo.delete_expense(user_id, expense_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"deleted": True}
