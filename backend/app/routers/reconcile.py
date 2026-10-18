"""Reconciliation endpoint (T7). Matches non-cash expenses to bank txns and
persists the links. Cash is skipped by design. Also exposes the current
reconciliation state (matched pairs + what's still open) and manual match/unmatch
so the user can fix or make links by hand from the results popup."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..models import BankNoReceiptRequest, ManualMatchRequest
from ..services import reconciliation
from .. import repository as repo

router = APIRouter(prefix="/reconcile", tags=["reconcile"])


def _day_diff(a, b) -> int | None:
    try:
        return abs((date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)
    except (ValueError, TypeError):
        return None


def _build_state(user_id: str) -> dict:
    """The current reconciliation picture, read fresh from the DB: every matched
    expense<->bank pair, the non-cash expenses still unmatched, and the bank
    purchases still waiting for a receipt. Drives the results popup."""
    expenses = repo.list_expenses(user_id)
    bank = repo.list_bank_transactions(user_id)
    bank_by_id = {t["id"]: t for t in bank}
    non_cash = [e for e in expenses if e.get("source") != "cash"]

    pairs = []
    for e in non_cash:
        tid = e.get("matched_transaction_id")
        if tid and tid in bank_by_id:
            t = bank_by_id[tid]
            pairs.append(
                {
                    "expense": e,
                    "transaction": t,
                    "amount_diff": round(abs(abs(float(t["amount"])) - abs(float(e["amount"]))), 2),
                    "day_diff": _day_diff(t.get("txn_date"), e.get("expense_date")),
                }
            )
    matched_ids = {p["expense"]["id"] for p in pairs}
    unmatched_expenses = [e for e in non_cash if e["id"] not in matched_ids]
    unmatched_bank = [
        t
        for t in bank
        if reconciliation.is_reconcilable(t)
        and not t.get("matched_expense_id")
        and not t.get("no_receipt")
    ]
    return {
        "pairs": pairs,
        "unmatched_expense_list": unmatched_expenses,
        "unmatched_bank_list": unmatched_bank,
        "matched": len(pairs),
        "unmatched_expenses": len(unmatched_expenses),
        "unmatched_bank": len(unmatched_bank),
        "cash_skipped": len([e for e in expenses if e.get("source") == "cash"]),
    }


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

    # `newly_matched` = how many this run just linked (for the toast); the rest of the
    # payload is the full fresh state for the results popup.
    state = _build_state(user_id)
    state["newly_matched"] = len(result.matches)
    return state


@router.get("/state")
def reconcile_state(user_id: str = Depends(get_current_user_id)) -> dict:
    """The current reconciliation state without running the matcher (used to refresh
    the popup after a manual match/unmatch)."""
    return _build_state(user_id)


def _owned_expense(user_id: str, expense_id: str) -> dict:
    for e in repo.list_expenses(user_id):
        if e["id"] == expense_id:
            return e
    raise HTTPException(status_code=404, detail="Expense not found.")


@router.post("/match")
def manual_match(
    body: ManualMatchRequest, user_id: str = Depends(get_current_user_id)
) -> dict:
    """Manually link an expense to a bank transaction."""
    if not body.transaction_id:
        raise HTTPException(status_code=400, detail="transaction_id is required.")
    exp = _owned_expense(user_id, body.expense_id)
    if exp.get("source") == "cash":
        raise HTTPException(status_code=400, detail="Cash expenses aren't reconciled.")
    # Free the transaction from any prior expense, and the expense from any prior txn.
    if exp.get("matched_transaction_id") and exp["matched_transaction_id"] != body.transaction_id:
        repo.update_bank_transaction(
            user_id, exp["matched_transaction_id"], {"matched_expense_id": None}
        )
    repo.update_expense(
        user_id,
        body.expense_id,
        {"reconciled": True, "matched_transaction_id": body.transaction_id},
    )
    repo.update_bank_transaction(
        user_id, body.transaction_id, {"matched_expense_id": body.expense_id}
    )
    return _build_state(user_id)


@router.post("/no-receipt")
def set_no_receipt(
    body: BankNoReceiptRequest, user_id: str = Depends(get_current_user_id)
) -> dict:
    """Acknowledge a bank payment as a no-receipt (online) payment, taking it out of
    the reconciliation cycle (or restore it with no_receipt=false)."""
    repo.update_bank_transaction(user_id, body.transaction_id, {"no_receipt": body.no_receipt})
    return _build_state(user_id)


@router.post("/unmatch")
def manual_unmatch(
    body: ManualMatchRequest, user_id: str = Depends(get_current_user_id)
) -> dict:
    """Undo a link between an expense and its bank transaction."""
    exp = _owned_expense(user_id, body.expense_id)
    tid = body.transaction_id or exp.get("matched_transaction_id")
    repo.update_expense(
        user_id, body.expense_id, {"reconciled": False, "matched_transaction_id": None}
    )
    if tid:
        repo.update_bank_transaction(user_id, tid, {"matched_expense_id": None})
    return _build_state(user_id)
