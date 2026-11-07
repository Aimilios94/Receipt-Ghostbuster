"""Pure helpers behind hand edits: changing how an expense was paid, undoing a
delete, and finding an expense by the name of the photo it was read from.

Kept DB-free so the rules are unit-tested; the routers do the reads and writes.
"""
from __future__ import annotations

from typing import Any

# How an expense was paid, as the Edit form offers it. "other_card" is a card that
# isn't on the imported bank statement: stored as source "card" with the D28
# no_bank_match flag, so it never waits for a bank line.
PAID_WITH = ("card", "other_card", "cash")


def paid_with(expense: dict[str, Any]) -> str:
    if expense.get("source") == "cash":
        return "cash"
    return "other_card" if expense.get("no_bank_match") else "card"


def payment_change(current: dict[str, Any], new: str) -> tuple[dict[str, Any], str | None]:
    """The expense patch for a change of payment method, plus the bank line to free.

    Cash never reconciles (D3) and another card isn't on the statement, so moving a
    row to either drops its bank match. Moving to your card starts it unreconciled,
    ready to match. Returns ({}, None) when nothing changes.
    """
    if new not in PAID_WITH:
        raise ValueError(f"paid_with must be one of {PAID_WITH}")
    if paid_with(current) == new:
        return {}, None
    if new == "card":
        return {"source": "card", "no_bank_match": False}, None
    patch = {
        "source": "cash" if new == "cash" else "card",
        "reconciled": False,
        "matched_transaction_id": None,
        "no_bank_match": new == "other_card",
    }
    return patch, current.get("matched_transaction_id")


# Columns a deleted expense is restored with. user_id is always the caller's.
_EXPENSE_COLS = (
    "id", "source", "input_method", "vendor", "amount", "currency", "expense_date",
    "category", "vat_amount", "vat_rate", "note", "receipt_image_url", "confidence",
    "status", "reconciled", "matched_transaction_id", "raw_extraction", "created_at",
    "no_bank_match",
)
_LINE_COLS = ("description", "quantity", "unit_price", "amount", "vat_rate", "vat_amount", "position")


def restorable(expense: dict[str, Any], line_items: list[dict[str, Any]] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The row and line items to re-insert when a delete is undone.

    Only known columns are kept, so a snapshot can't set another user or a column
    that doesn't exist. The row keeps its id, so links to it stay valid.
    """
    if not expense.get("id") or expense.get("amount") is None or not expense.get("expense_date"):
        raise ValueError("snapshot needs id, amount and expense_date")
    row = {k: expense[k] for k in _EXPENSE_COLS if k in expense}
    lines = [{k: li.get(k) for k in _LINE_COLS} for li in (line_items or [])]
    return row, lines


def photo_names(expenses: list[dict[str, Any]], traces: list[dict[str, Any]]) -> dict[str, str]:
    """expense id -> the file name of the photo it was read from.

    A name saved on the expense wins. Otherwise the newest read trace that names both
    the expense and a file is used (traces are newest first). Rows uploaded before
    names were recorded have none.
    """
    ids = {e["id"] for e in expenses}
    names: dict[str, str] = {}
    for t in traces:
        meta = t.get("meta") or {}
        eid, name = meta.get("expense_id"), meta.get("filename")
        if eid in ids and name and eid not in names:
            names[eid] = str(name)
    for e in expenses:
        saved = (e.get("raw_extraction") or {}).get("source_filename")
        if saved:
            names[e["id"]] = str(saved)
    return names
