"""Subscription endpoints (Phase 2, T12–T13).

POST /subscriptions/detect   — scan ledger + bank for recurring charges, upsert.
GET  /subscriptions          — list stored subscriptions (+ staleness).
POST /subscriptions/{id}     — update user-owned fields (status, usage_note, saved).

Detection is deterministic (services/subscriptions.py); the LLM is not involved.
Re-running detect refreshes detection-derived fields but preserves the user's
own status/usage_note (see repository.upsert_subscriptions).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user_id
from ..models import SubscriptionUpdate
from ..services import subscriptions as sub_service
from .. import repository as repo

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("/detect")
def detect(user_id: str = Depends(get_current_user_id)) -> dict:
    expenses = repo.list_expenses(user_id)
    bank_txns = repo.list_bank_transactions(user_id)
    detected = sub_service.detect_subscriptions(expenses, bank_txns)
    repo.upsert_subscriptions(user_id, detected)
    # Return the freshly-stored rows (with user status) annotated with staleness.
    stored = sub_service.annotate(repo.list_subscriptions(user_id))
    return {"detected": len(detected), "subscriptions": stored}


@router.get("")
def list_subscriptions(user_id: str = Depends(get_current_user_id)) -> dict:
    return {"subscriptions": sub_service.annotate(repo.list_subscriptions(user_id))}


@router.post("/{sub_id}")
def update_subscription(
    sub_id: str,
    body: SubscriptionUpdate,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    row = repo.update_subscription(user_id, sub_id, patch)
    return {"subscription": row}
