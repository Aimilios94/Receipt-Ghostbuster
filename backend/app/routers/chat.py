"""Chatbot endpoint (v0.5) — natural-language Q&A over the user's ledger.

Read-only. The model answers only via the analytics tools (services/chat.py →
services/analytics.py); every number is computed in code, never by the model.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..services import chat as chat_service, monitoring
from .. import repository as repo

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


@router.post("")
def ask(
    body: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Ask a question about your ledger.")
    if settings.llm_provider != "openai" or not settings.llm_configured:
        raise HTTPException(
            status_code=503,
            detail="The assistant needs the OpenAI provider configured (set OPENAI_API_KEY, LLM_PROVIDER=openai).",
        )
    line_items_by_expense: dict[str, list] = {}
    for li in repo.list_all_line_items(user_id):
        line_items_by_expense.setdefault(li.get("expense_id"), []).append(li)
    data = {
        "expenses": repo.list_expenses(user_id),
        "bank": repo.list_bank_transactions(user_id),
        "subscriptions": repo.list_subscriptions(user_id),
        "line_items": line_items_by_expense,
    }
    try:
        return chat_service.answer_question(
            body.message, [m.model_dump() for m in body.history], data, settings
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean message (with CORS headers)
        monitoring.capture(exc, surface="chat.answer")
        raise HTTPException(status_code=502, detail=f"The assistant couldn't answer: {str(exc)[:200]}") from exc
