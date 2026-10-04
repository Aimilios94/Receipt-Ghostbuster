"""Data-access helpers over the Supabase client.

The backend uses the service_role key (RLS bypassed), so every function here sets
or filters `user_id` explicitly. Keeping these in one place keeps the routers thin.
"""
from __future__ import annotations

from typing import Any

from .supabase_client import get_supabase


def list_expenses(user_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
    q = get_supabase().table("expenses").select("*").eq("user_id", user_id)
    if status:
        q = q.eq("status", status)
    return q.order("expense_date", desc=True).execute().data or []


def list_bank_transactions(user_id: str) -> list[dict[str, Any]]:
    return (
        get_supabase()
        .table("bank_transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("txn_date", desc=True)
        .execute()
        .data
        or []
    )


def insert_expense(user_id: str, row: dict[str, Any]) -> dict[str, Any]:
    row = {**row, "user_id": user_id}
    return get_supabase().table("expenses").insert(row).execute().data[0]


def update_expense(user_id: str, expense_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    data = (
        get_supabase()
        .table("expenses")
        .update(patch)
        .eq("user_id", user_id)
        .eq("id", expense_id)
        .execute()
        .data
    )
    return data[0] if data else {}


def insert_bank_transactions(user_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = [{**r, "user_id": user_id} for r in rows]
    return get_supabase().table("bank_transactions").insert(payload).execute().data or []


def update_bank_transaction(user_id: str, txn_id: str, patch: dict[str, Any]) -> None:
    get_supabase().table("bank_transactions").update(patch).eq("user_id", user_id).eq(
        "id", txn_id
    ).execute()


DEFAULT_CATEGORIES = [
    "Groceries",
    "Dining & Cafes",
    "Transport & Fuel",
    "Utilities",
    "Rent & Housing",
    "Software & Subscriptions",
    "Office & Supplies",
    "Travel",
    "Health & Pharmacy",
    "Entertainment",
    "Professional Services",
    "Taxes & Fees",
    "Income",
    "Uncategorized",
]


def seed_default_categories(user_id: str) -> list[dict[str, Any]]:
    """Insert the default category list for a user (idempotent via unique name)."""
    rows = [{"user_id": user_id, "name": name} for name in DEFAULT_CATEGORIES]
    return (
        get_supabase()
        .table("categories")
        .upsert(rows, on_conflict="user_id,name")
        .execute()
        .data
        or []
    )


def list_categories(user_id: str) -> list[dict[str, Any]]:
    data = (
        get_supabase()
        .table("categories")
        .select("*")
        .eq("user_id", user_id)
        .order("name")
        .execute()
        .data
        or []
    )
    if not data:
        # First use for this owner — provision the default set.
        seed_default_categories(user_id)
        data = (
            get_supabase()
            .table("categories")
            .select("*")
            .eq("user_id", user_id)
            .order("name")
            .execute()
            .data
            or []
        )
    return data


def upload_receipt(user_id: str, filename: str, content: bytes, content_type: str) -> str:
    """Store a receipt image under '<user_id>/<filename>' and return a signed URL."""
    from .config import get_settings

    bucket = get_settings().supabase_receipts_bucket
    path = f"{user_id}/{filename}"
    storage = get_supabase().storage.from_(bucket)
    storage.upload(
        path,
        content,
        {"content-type": content_type, "upsert": "true"},
    )
    # Signed URL valid for 1 year (bucket is private).
    signed = storage.create_signed_url(path, 60 * 60 * 24 * 365)
    return signed.get("signedURL") or signed.get("signedUrl") or path
