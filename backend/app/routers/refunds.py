"""Refund actions — the drafted cancel/refund emails (Phase 2, T14–T15).

GET  /refund-actions        — list drafts/handled actions.
POST /refund-actions/{id}   — edit the draft or mark it handled (records savings).

Nothing here sends email. 'done' means the user handled it (via the Gmail draft
that n8n creates, or manually). Realized savings are recorded here, not on the
subscription row.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..models import RefundActionUpdate
from ..services import monitoring
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


@router.post("/{action_id}/deliver")
def deliver_to_gmail(
    action_id: str,
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Push an approved draft to n8n, which creates a Gmail DRAFT (never sends).

    n8n owns the Gmail credential; this just forwards subject/body/recipient to
    the workflow's webhook. Marks the action 'sent' (= saved to Gmail drafts).
    """
    if not settings.n8n_configured:
        raise HTTPException(
            status_code=503,
            detail="n8n is not connected. Set N8N_WEBHOOK_URL in backend/.env to the "
            "imported workflow's webhook URL (e.g. http://localhost:5678/webhook/refund-draft).",
        )
    action = next((a for a in repo.list_refund_actions(user_id) if a["id"] == action_id), None)
    if not action:
        raise HTTPException(status_code=404, detail="Refund action not found")

    payload = {
        "to": action.get("recipient") or "",
        "subject": action.get("subject") or "",
        "message": action.get("email_draft") or "",
    }
    try:
        resp = httpx.post(settings.n8n_webhook_url, json=payload, timeout=20)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        monitoring.capture(exc, surface="refunds.n8n_webhook")
        raise HTTPException(status_code=502, detail=f"n8n webhook call failed: {exc}") from exc

    row = repo.update_refund_action(user_id, action_id, {"status": "sent"})
    return {"refund_action": row, "delivered": True}
