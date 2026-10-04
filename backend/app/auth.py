"""Resolve the current owner (user_id) for a request.

Priority:
1. A Supabase JWT in the Authorization header, verified with SUPABASE_JWT_SECRET.
2. If no/invalid token AND DEV_USER_ID is set, fall back to that id (demo mode).
Otherwise 401. This lets the app run end-to-end before the frontend auth is wired,
while still doing real verification the moment a secret + token are present.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from .config import Settings, get_settings


def get_current_user_id(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if token and settings.supabase_jwt_secret:
        import jwt  # PyJWT

        try:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.PyJWTError as exc:  # pragma: no cover - exercised via API
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token missing subject (sub).")
        return sub

    if settings.dev_user_id:
        return settings.dev_user_id

    raise HTTPException(
        status_code=401,
        detail=(
            "Not authenticated. Send a Supabase JWT as 'Authorization: Bearer <token>' "
            "(requires SUPABASE_JWT_SECRET), or set DEV_USER_ID in backend/.env for demo mode."
        ),
    )
