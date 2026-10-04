"""Receipt Ghostbuster API entrypoint.

Run locally:
    cd backend
    uvicorn app.main:app --reload
Docs at http://localhost:8000/docs
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import (
    bank,
    close,
    exceptions,
    expenses,
    extract,
    health,
    reconcile,
    refunds,
    subscriptions,
)

settings = get_settings()

app = FastAPI(
    title="Receipt Ghostbuster API",
    version="0.1.0",
    description="Personal money assistant: track, categorize, VAT-split, reconcile, close.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(expenses.router)
app.include_router(extract.router)
app.include_router(bank.router)
app.include_router(reconcile.router)
app.include_router(exceptions.router)
app.include_router(close.router)
app.include_router(subscriptions.router)
app.include_router(refunds.router)


@app.get("/", tags=["health"])
def root() -> dict:
    return {"app": "Receipt Ghostbuster", "docs": "/docs", "health": "/health"}
