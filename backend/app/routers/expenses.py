"""Expense endpoints: manual/cash entry (T3), listing, and the review queue (T5)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..models import ExpenseCategoryUpdate, ExpenseCreate, ExpenseStatusUpdate
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


@router.get("/line-items")
def all_line_items(user_id: str = Depends(get_current_user_id)) -> dict:
    """Every line item the user owns (joined to the ledger client-side for the
    VAT-by-rate breakdown). Declared before /{expense_id}/... — distinct path."""
    return {"line_items": repo.list_all_line_items(user_id)}


@router.get("/{expense_id}/line-items")
def expense_line_items(
    expense_id: str,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """One receipt's itemized lines + its VAT summed per rate in code."""
    items = repo.list_line_items(user_id, expense_id)
    breakdown = vat.vat_breakdown([i for i in items if i.get("amount") is not None])
    return {"line_items": items, "vat_breakdown": breakdown}


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

        if body.line_items is not None:
            # Multi-rate breakdown the user entered: VAT summed PER RATE in code.
            # The lines become the source of truth for amount + VAT.
            rows = [
                {
                    "description": li.description,
                    "quantity": li.quantity,
                    "unit_price": li.unit_price,
                    "amount": li.amount,
                    "vat_rate": li.vat_rate,
                    "vat_amount": vat.line_vat(li.amount, li.vat_rate),
                    "position": idx,
                }
                for idx, li in enumerate(body.line_items)
            ]
            breakdown = vat.vat_breakdown(rows)
            repo.replace_line_items(user_id, expense_id, rows)
            # The stated amount (the receipt's TOTAL A PAGAR) is the full amount paid and
            # wins; the VAT lines only supply the VAT split. They should reconcile, but a
            # reliable total must not be overwritten by a line-sum that missed a rate.
            patch["amount"] = body.amount or breakdown["gross"]
            patch["vat_amount"] = breakdown["vat_amount"]
            if breakdown["rate_count"] > 0:
                dominant = max(
                    (r for r in breakdown["rates"] if r["rate"] > 0),
                    key=lambda r: r["gross"],
                )
                patch["vat_rate"] = dominant["rate"]
            else:
                # All lines are zero-rated/exempt (e.g. tobacco at 0%). Record an
                # EXPLICIT 0% so it reads as "confirmed zero-rated", not "VAT missing".
                patch["vat_rate"] = 0
        elif body.vat_rate is not None or body.vat_amount is not None:
            amount = body.amount or patch.get("amount")
            if amount:
                vat_info = vat.resolve_vat(amount, body.vat_rate, body.vat_amount)
                patch["vat_amount"] = vat_info["vat_amount"]
                patch["vat_rate"] = vat_info["vat_rate"]
    updated = repo.update_expense(user_id, expense_id, patch)
    return {"expense": updated}


@router.post("/{expense_id}/status")
def set_status(
    expense_id: str,
    body: ExpenseStatusUpdate,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Change just the ledger status (e.g. move a posted row back to review)."""
    updated = repo.update_expense(user_id, expense_id, {"status": body.status})
    if not updated:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"expense": updated}


@router.post("/{expense_id}/category")
def set_category(
    expense_id: str,
    body: ExpenseCategoryUpdate,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Re-categorize an expense straight from the Ledger category column."""
    updated = repo.update_expense(user_id, expense_id, {"category": body.category})
    if not updated:
        raise HTTPException(status_code=404, detail="Expense not found")
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
