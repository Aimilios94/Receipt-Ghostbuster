"""Receipt Ghostbuster API entrypoint.

Run locally:
    cd backend
    uvicorn app.main:app --port 8000
Docs at http://localhost:8000/docs
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import get_settings
from .routers import (
    bank,
    breakdown,
    chat,
    close,
    exceptions,
    expenses,
    extract,
    health,
    insights,
    metrics,
    reconcile,
    refunds,
    subscriptions,
)
from .services import monitoring

settings = get_settings()

# Initialise Sentry (opt-in) BEFORE the app is created so its ASGI/FastAPI
# integration wraps the app and auto-captures unhandled errors. No-op without a DSN.
monitoring.init_sentry_if_enabled(settings)

app = FastAPI(
    title="Receipt Ghostbuster API",
    version=__version__,
    description="Personal money assistant: track, categorize, VAT-split, reconcile, close.",
)

READ_ONLY_MESSAGE = (
    "This is a read-only demo with invented data, so changes are turned off. "
    "Run the app locally to try them."
)
# The one POST a read-only demo still allows: the Advice feed refreshes its insights by POST
# when a page loads. It's rule-based with no model call (D36), and it only rewrites insight
# rows from the data already there.
READ_ONLY_ALLOWED = {("POST", "/insights/generate")}


def refused_in_read_only(method: str, path: str) -> bool:
    """Whether a read-only demo refuses this request: anything but a read, unless allowed above."""
    method = method.upper()
    if method in {"GET", "HEAD", "OPTIONS"}:
        return False
    return (method, path.rstrip("/") or "/") not in READ_ONLY_ALLOWED


# Registered before CORS, so CORS wraps it and the browser can read the refusal.
@app.middleware("http")
async def read_only_demo(request: Request, call_next):
    if get_settings().demo_read_only and refused_in_read_only(request.method, request.url.path):
        return JSONResponse({"detail": READ_ONLY_MESSAGE}, status_code=403)
    return await call_next(request)


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
app.include_router(breakdown.router)
app.include_router(chat.router)
app.include_router(reconcile.router)
app.include_router(exceptions.router)
app.include_router(close.router)
app.include_router(subscriptions.router)
app.include_router(refunds.router)
app.include_router(metrics.router)
app.include_router(insights.router)


@app.get("/", tags=["health"])
def root() -> dict:
    return {"app": "Receipt Ghostbuster", "docs": "/docs", "health": "/health"}
