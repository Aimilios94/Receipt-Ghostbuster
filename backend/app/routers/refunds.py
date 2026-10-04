"""Refund actions — the drafted cancel/refund emails (Phase 2, T14–T15).

GET  /refund-actions        — list drafts/handled actions.
POST /refund-actions/{id}   — edit the draft or mark it handled (records savings).

Nothing here sends email. 'done' means the user handled it (via the Gmail draft
that n8n creates, or manually). Realized savings are recorded here, not on the
subscription row.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user_id
from ..models import RefundActionUpdate
from .. import repository as repo

router = APIRouter(prefix="/refund-actions", tags=["refunds"])


@router.get("")
def list_refund_actions(user_id: str = Depends(get_current_user_id)) -> dict:
    return {"refund_actions": repo.list_refund_actions(user_id)}


@router.post("/{action_id}")
def update_refund_action(
    action_id: str,
    body: RefundActionUpdate,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    row = repo.update_refund_action(user_id, action_id, patch)
    return {"refund_action": row}
