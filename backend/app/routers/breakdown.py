"""Spending breakdown endpoint — by vendor, and third-party transfers.

Surfaced from both the Reconciliation and Ledger pages. Deterministic, DB-read
only; all totals are summed in code (services/breakdown.py).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user_id
from ..services import breakdown
from .. import repository as repo

router = APIRouter(prefix="/breakdown", tags=["breakdown"])


@router.get("")
def get_breakdown(user_id: str = Depends(get_current_user_id)) -> dict:
    expenses = repo.list_expenses(user_id)
    bank_txns = repo.list_bank_transactions(user_id)
    return {
        "vendors": breakdown.vendor_breakdown(expenses),
        "third_parties": breakdown.third_party_breakdown(bank_txns),
        "own_movements": breakdown.own_movement_breakdown(bank_txns),
    }
