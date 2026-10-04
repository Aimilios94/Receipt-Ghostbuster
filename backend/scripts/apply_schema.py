"""Apply db/schema.sql to the Supabase project via the Management API.

Usage (from backend/):
    python scripts/apply_schema.py

Requires in .env:
    SUPABASE_URL              (to derive the project ref)
    SUPABASE_ACCESS_TOKEN     (personal access token, starts with 'sbp_')

This is the automated alternative to pasting schema.sql into the SQL editor.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
REPO = BACKEND.parent
SCHEMA = REPO / "db" / "schema.sql"


def main() -> int:
    load_dotenv(BACKEND / ".env")

    url = os.environ.get("SUPABASE_URL", "")
    token = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
    if not url or not token:
        print("ERROR: set SUPABASE_URL and SUPABASE_ACCESS_TOKEN in backend/.env")
        return 2

    ref = urlparse(url).hostname.split(".")[0]  # <ref>.supabase.co
    sql = SCHEMA.read_text(encoding="utf-8")

    print(f"Applying {SCHEMA} to project '{ref}' ...")
    resp = httpx.post(
        f"https://api.supabase.com/v1/projects/{ref}/database/query",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=120,
    )
    if resp.status_code >= 300:
        print(f"FAILED ({resp.status_code}): {resp.text[:500]}")
        return 1
    print("OK — schema applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
