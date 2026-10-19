"""Data-access helpers over the Supabase client.

The backend uses the service_role key (RLS bypassed), so every function here sets
or filters `user_id` explicitly. Keeping these in one place keeps the routers thin.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .supabase_client import get_supabase

# A duplicate upload shares the vendor and the exact total; the DATE is the
# least reliable field (it's the most-misread — see DECISIONS D16), so two
# photos of the same receipt often disagree on the date. We therefore match on
# vendor + amount within a generous date window rather than an exact date.
DUPLICATE_WINDOW_DAYS = 30


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _vendor_tokens(vendor: str | None) -> list[str]:
    """Lower-cased alphanumeric tokens of a vendor name, so 'Pingo Doce - PD
    Olaias' -> ['pingo', 'doce', 'pd', 'olaias']."""
    if not vendor:
        return []
    cleaned = "".join(ch if ch.isalnum() else " " for ch in vendor.lower())
    return cleaned.split()


def _vendor_matches(a: str | None, b: str | None) -> bool:
    """Same store? The model reads the vendor inconsistently — sometimes just the
    brand ('Pingo Doce'), sometimes with the branch ('Pingo Doce - PD Olaias') —
    so we match when the shorter token list is a leading prefix of the longer one
    (brand-prefix), not on an exact string."""
    ta, tb = _vendor_tokens(a), _vendor_tokens(b)
    if not ta or not tb:
        return False
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return long[: len(short)] == short


def match_duplicate_rows(
    rows: list[dict[str, Any]],
    vendor: str | None,
    amount: float | None,
    expense_date: str | None,
    *,
    window_days: int = DUPLICATE_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Pure matcher (no DB): rows that look like the SAME purchase as the given
    vendor+amount. Same vendor + same total to the cent is the fingerprint; the
    dates must fall within ``window_days`` of each other, UNLESS either date is
    missing/unparseable (then vendor+amount alone flags it, since the date is
    the weak signal — better to surface for a human check than to miss it)."""
    if not vendor or amount is None:
        return []
    new_d = _parse_iso_date(expense_date)
    out: list[dict[str, Any]] = []
    for r in rows:
        if not _vendor_matches(r.get("vendor"), vendor):
            continue
        if abs(float(r.get("amount") or 0) - float(amount)) >= 0.005:
            continue
        existing_d = _parse_iso_date(r.get("expense_date"))
        if new_d and existing_d and abs((existing_d - new_d).days) > window_days:
            continue
        out.append(r)
    return out


def find_duplicates(
    user_id: str, vendor: str | None, amount: float | None, expense_date: str | None
) -> list[dict[str, Any]]:
    """Existing ledger rows that look like the SAME purchase (same vendor +
    amount, within ~30 days) — used to flag a likely duplicate at upload time,
    before posting. Keyed on the strong fields (vendor + exact total) with a
    date window, so a re-upload with a misread date is still caught."""
    if not vendor or amount is None:
        return []
    rows = (
        get_supabase()
        .table("expenses")
        .select("*")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    return match_duplicate_rows(rows, vendor, amount, expense_date)


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


def delete_expense(user_id: str, expense_id: str) -> bool:
    data = (
        get_supabase()
        .table("expenses")
        .delete()
        .eq("user_id", user_id)
        .eq("id", expense_id)
        .execute()
        .data
    )
    return bool(data)


# --- Line items (per-line VAT) ---------------------------------------------
def insert_line_items(
    user_id: str, expense_id: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Persist a receipt's line items (each carrying its own VAT rate). Rows
    cascade-delete with the parent expense via the FK."""
    if not items:
        return []
    payload = [
        {**item, "user_id": user_id, "expense_id": expense_id} for item in items
    ]
    return (
        get_supabase().table("expense_line_items").insert(payload).execute().data or []
    )


def delete_line_items(user_id: str, expense_id: str) -> None:
    get_supabase().table("expense_line_items").delete().eq("user_id", user_id).eq(
        "expense_id", expense_id
    ).execute()


def replace_line_items(
    user_id: str, expense_id: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Swap an expense's line items for a new set (used when the user edits the
    VAT breakdown in the review queue). Delete-then-insert, scoped to the owner."""
    delete_line_items(user_id, expense_id)
    return insert_line_items(user_id, expense_id, items)


def list_line_items(user_id: str, expense_id: str) -> list[dict[str, Any]]:
    return (
        get_supabase()
        .table("expense_line_items")
        .select("*")
        .eq("user_id", user_id)
        .eq("expense_id", expense_id)
        .order("position")
        .execute()
        .data
        or []
    )


def list_all_line_items(user_id: str) -> list[dict[str, Any]]:
    """Every line item the user owns — the frontend joins these to the ledger by
    expense_id to aggregate VAT by rate across many receipts."""
    return (
        get_supabase()
        .table("expense_line_items")
        .select("*")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )


def list_line_items_for(user_id: str, expense_ids: list[str]) -> list[dict[str, Any]]:
    """All line items for a set of expenses (one query), for dashboard/ledger
    VAT-by-rate aggregation across many receipts."""
    if not expense_ids:
        return []
    return (
        get_supabase()
        .table("expense_line_items")
        .select("*")
        .eq("user_id", user_id)
        .in_("expense_id", expense_ids)
        .execute()
        .data
        or []
    )


def insert_bank_transactions(user_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = [{**r, "user_id": user_id} for r in rows]
    return get_supabase().table("bank_transactions").insert(payload).execute().data or []


def update_bank_transaction(user_id: str, txn_id: str, patch: dict[str, Any]) -> None:
    get_supabase().table("bank_transactions").update(patch).eq("user_id", user_id).eq(
        "id", txn_id
    ).execute()


# --- bank statements (one row per imported file) ----------------------------

def insert_bank_statement(user_id: str, row: dict[str, Any]) -> dict[str, Any]:
    data = (
        get_supabase()
        .table("bank_statements")
        .insert({**row, "user_id": user_id})
        .execute()
        .data
        or []
    )
    return data[0] if data else {}


def list_bank_statements(user_id: str) -> list[dict[str, Any]]:
    return (
        get_supabase()
        .table("bank_statements")
        .select("*")
        .eq("user_id", user_id)
        .order("uploaded_at", desc=True)
        .execute()
        .data
        or []
    )


def get_bank_statement(user_id: str, statement_id: str) -> dict[str, Any] | None:
    data = (
        get_supabase()
        .table("bank_statements")
        .select("*")
        .eq("user_id", user_id)
        .eq("id", statement_id)
        .execute()
        .data
        or []
    )
    return data[0] if data else None


def list_statement_transactions(user_id: str, statement_id: str) -> list[dict[str, Any]]:
    return (
        get_supabase()
        .table("bank_transactions")
        .select("*")
        .eq("user_id", user_id)
        .eq("statement_id", statement_id)
        .order("txn_date", desc=False)
        .execute()
        .data
        or []
    )


def delete_bank_statement(user_id: str, statement_id: str) -> None:
    """Delete a statement and (via FK cascade) its transactions. First clear any
    expense links to those transactions so no expense points at a deleted row."""
    sb = get_supabase()
    txns = (
        sb.table("bank_transactions")
        .select("id")
        .eq("user_id", user_id)
        .eq("statement_id", statement_id)
        .execute()
        .data
        or []
    )
    tids = [t["id"] for t in txns]
    if tids:
        sb.table("expenses").update({"matched_transaction_id": None, "reconciled": False}).eq(
            "user_id", user_id
        ).in_("matched_transaction_id", tids).execute()
    sb.table("bank_statements").delete().eq("user_id", user_id).eq("id", statement_id).execute()


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
    "Tobacco",
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


# --- Phase 2: subscriptions (Refund Hunter) --------------------------------
def list_subscriptions(user_id: str) -> list[dict[str, Any]]:
    return (
        get_supabase()
        .table("subscriptions")
        .select("*")
        .eq("user_id", user_id)
        .order("annual_cost", desc=True)
        .execute()
        .data
        or []
    )


def upsert_subscriptions(user_id: str, subs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upsert detection-derived columns only, so user-owned fields (status,
    usage_note) survive re-detection. Keyed on (user_id, vendor, amount)."""
    if not subs:
        return []
    detection_cols = {
        "vendor", "amount", "cadence", "annual_cost",
        "occurrences", "first_seen", "last_seen", "source",
    }
    rows = [
        {"user_id": user_id, **{k: v for k, v in s.items() if k in detection_cols}}
        for s in subs
    ]
    return (
        get_supabase()
        .table("subscriptions")
        .upsert(rows, on_conflict="user_id,vendor,amount")
        .execute()
        .data
        or []
    )


def get_subscription(user_id: str, sub_id: str) -> dict[str, Any]:
    data = (
        get_supabase()
        .table("subscriptions")
        .select("*")
        .eq("user_id", user_id)
        .eq("id", sub_id)
        .limit(1)
        .execute()
        .data
    )
    return data[0] if data else {}


# --- Phase 2: refund actions (drafts) --------------------------------------
def insert_refund_action(user_id: str, row: dict[str, Any]) -> dict[str, Any]:
    row = {**row, "user_id": user_id}
    return get_supabase().table("refund_actions").insert(row).execute().data[0]


def list_refund_actions(user_id: str) -> list[dict[str, Any]]:
    return (
        get_supabase()
        .table("refund_actions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )


def update_refund_action(user_id: str, action_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    data = (
        get_supabase()
        .table("refund_actions")
        .update(patch)
        .eq("user_id", user_id)
        .eq("id", action_id)
        .execute()
        .data
    )
    return data[0] if data else {}


def update_subscription(user_id: str, sub_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    data = (
        get_supabase()
        .table("subscriptions")
        .update(patch)
        .eq("user_id", user_id)
        .eq("id", sub_id)
        .execute()
        .data
    )
    return data[0] if data else {}


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
