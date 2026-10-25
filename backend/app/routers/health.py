"""Health + readiness. Works with zero secrets so you can verify the app boots."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Report liveness and which integrations are configured (not the secrets)."""
    return {
        "status": "ok",
        "config": {
            "supabase_configured": settings.supabase_configured,
            "llm_provider": settings.llm_provider,
            "llm_configured": settings.llm_configured,
            "confidence_threshold": settings.confidence_threshold,
            "default_currency": settings.default_currency,
            "n8n_configured": settings.n8n_configured,
            "langsmith_tracing": settings.langsmith_configured,
            "sentry_enabled": settings.sentry_configured,
            "chat_cache_enabled": settings.chat_cache_enabled,
            "auth_mode": "jwt" if settings.supabase_jwt_secret else ("dev" if settings.dev_user_id else "none"),
        },
    }
