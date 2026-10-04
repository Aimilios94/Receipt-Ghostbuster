"""Subscription detection endpoints (Phase 2, T12).

POST /subscriptions/detect  — scan the ledger + bank for recurring charges,
                              upsert into `subscriptions`, return them.
GET  /subscriptions         — list stored subscriptions.

Detection is deterministic (services/subscriptions.py); the LLM is not involved.
Re-running detect refreshes detection-derived fields but preserves the user's
own status/usage_note (see repository.upsert_subscriptions).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user_id
from ..services import subscriptions as sub_service
from .. import repository as repo

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("/detect")
def detect(user_id: str = Depends(get_current_user_id)) -> dict:
    expenses = repo.list_expenses(user_id)
    bank_txns = repo.list_bank_transactions(user_id)
    detected = sub_service.detect_subscriptions(expenses, bank_txns)
    stored = repo.upsert_subscriptions(user_id, detected)
    return {"detected": len(detected), "subscriptions": stored or detected}


@router.get("")
def list_subscriptions(user_id: str = Depends(get_current_user_id)) -> dict:
    return {"subscriptions": repo.list_subscriptions(user_id)}
