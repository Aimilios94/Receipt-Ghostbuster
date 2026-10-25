"""Advice / insights endpoints (v0.4).

POST /insights/generate  — derive the rule-based nudges for a month, upsert them
                           (preserving the user-owned `dismissed` flag), return
                           the active rows. Deterministic, no LLM — safe to call
                           on every page load. Mirrors POST /subscriptions/detect.
GET  /insights           — list stored insights for a month.
POST /insights/{id}      — dismiss / restore an insight.

All spend/budget/savings math is computed in code (services/insights.py).
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from ..auth import get_current_user_id
from ..models import InsightDismiss
from ..services import insights as insights_service
from .. import repository as repo

router = APIRouter(prefix="/insights", tags=["insights"])


@router.post("/generate")
def generate(
    month: str = Query(default=None, description="YYYY-MM; defaults to current month"),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    month = month or date.today().strftime("%Y-%m")
    expenses = repo.list_expenses(user_id)
    categories = repo.list_categories(user_id)
    subscriptions = repo.list_subscriptions(user_id)
    derived = insights_service.generate_insights(expenses, categories, subscriptions, month)
    repo.upsert_insights(user_id, derived)
    return {"generated": len(derived), "insights": repo.list_insights(user_id, month)}


@router.get("")
def list_insights(
    month: str = Query(default=None, description="YYYY-MM; defaults to current month"),
    include_dismissed: bool = False,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    month = month or date.today().strftime("%Y-%m")
    return {"insights": repo.list_insights(user_id, month, include_dismissed=include_dismissed)}


@router.post("/{insight_id}")
def dismiss_insight(
    insight_id: str,
    body: InsightDismiss,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    row = repo.update_insight(user_id, insight_id, {"dismissed": body.dismissed})
    return {"insight": row}
