"""Thin Supabase client wrapper.

Uses the service_role key (server-side only). service_role BYPASSES RLS, so every
query in the service layer must set/filter user_id explicitly — see db/schema.sql.
The client is created lazily so the app boots without credentials.

The client is created PER THREAD, not as a single shared singleton. FastAPI runs
our sync endpoints in a threadpool, so a heavy request (e.g. reconciliation, which
makes many Supabase calls) can run concurrently with the frontend's refetches.
Sharing one underlying httpx client across threads caused transient `WinError
10035` socket errors on Windows under that concurrency; a client per thread
removes the contention.
"""
from __future__ import annotations

import threading

from fastapi import HTTPException

from .config import get_settings

_local = threading.local()


def get_supabase():
    client = getattr(_local, "client", None)
    if client is not None:
        return client

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

    client = create_client(settings.supabase_url, settings.supabase_service_key)
    _local.client = client
    return client
