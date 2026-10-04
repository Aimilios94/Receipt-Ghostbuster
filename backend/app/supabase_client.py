"""Thin Supabase client wrapper.

Uses the service_role key (server-side only). service_role BYPASSES RLS, so every
query in the service layer must set/filter user_id explicitly — see db/schema.sql.
The client is created lazily so the app boots without credentials.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException

from .config import get_settings


@lru_cache
def get_supabase():
    settings = get_settings()
    if not settings.supabase_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "Supabase is not configured. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_KEY in backend/.env, then restart the API."
            ),
        )
    # Imported lazily so the package imports even if supabase isn't installed yet.
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_key)
