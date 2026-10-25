"""Spending breakdown — by vendor, and third-party transfers (sent / received).

Pure functions over plain dicts (like reconciliation.py / subscriptions.py), so
they are fully unit-testable and DB-free.

Two views the user asked for:
  - **By vendor** — every expense grouped by its vendor, with the total paid to
    each. Clean vendor names, includes cash. "Where my money went, per merchant."
  - **Third parties** — money moved to/from a *person* (a transfer), not a
    purchase. Grouped by counterparty and split into sent vs received, with totals.
    These live only in the bank statement (they're excluded from the expense
    ledger and from reconciliation, see D23), so they're derived from bank txns.
"""
from __future__ import annotations

from typing import Any

# Prefixes a bank statement puts before a transfer counterparty's name.
_TRANSFER_PREFIXES = ("transfer to ", "transfer from ", "to ", "from ")

# Transfers to the user's own Revolut (savings vaults, Revolut Ltd fees, etc.) are
# account movements, not money sent to a third party — excluded from that view.
_OWN_MOVEMENT_HINTS = ("revolut",)


def _amount(value: Any) -> float:
    try:
        return abs(float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def vendor_breakdown(expenses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expenses grouped by vendor: {vendor, count, total, items}, highest total
    first. `items` are the individual expenses (date, amount, note, category) behind
    the group, so a row can be expanded to its detail. Totals summed in code."""
    groups: dict[str, dict[str, Any]] = {}
    for e in expenses:
        vendor = (str(e.get("vendor") or "").strip()) or "Unknown"
        g = groups.setdefault(vendor.lower(), {"vendor": vendor, "count": 0, "total": 0.0, "items": []})
        g["count"] += 1
        g["total"] += _amount(e.get("amount"))
        g["items"].append(
            {
                "date": str(e.get("expense_date") or "")[:10],
                "amount": round(_amount(e.get("amount")), 2),
                "note": (str(e.get("note")).strip() if e.get("note") else None),
                "category": e.get("category"),
            }
        )
    rows = []
    for g in groups.values():
        g["items"].sort(key=lambda it: it["date"])
        rows.append(
            {"vendor": g["vendor"], "count": g["count"], "total": round(g["total"], 2), "items": g["items"]}
        )
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


def _is_own_movement(txn: dict[str, Any]) -> bool:
    """A transfer to the user's own Revolut (savings/fees), not a third party."""
    desc = (txn.get("description") or "").lower()
    return any(h in desc for h in _OWN_MOVEMENT_HINTS)


def _is_transfer_like(txn: dict[str, Any]) -> bool:
    """A transfer (to a person OR the user's own account) — not a card purchase
    or a top-up."""
    raw = txn.get("raw") or {}
    ttype = str(raw.get("Type") or raw.get("type") or "").strip().lower()
    if ttype == "transfer":
        return True
    desc = (txn.get("description") or "").strip().lower()
    return desc.startswith(_TRANSFER_PREFIXES)


def _is_transfer(txn: dict[str, Any]) -> bool:
    """A person-to-person transfer — a transfer that is NOT an own-account
    (Revolut) movement."""
    return _is_transfer_like(txn) and not _is_own_movement(txn)


def _counterparty(description: str | None) -> str:
    """Strip the 'Transfer to' / 'To' / 'from' prefix to get just the name."""
    d = (description or "").strip()
    low = d.lower()
    for pre in _TRANSFER_PREFIXES:
        if low.startswith(pre):
            return d[len(pre):].strip() or d
    return d or "—"


def _group_transfers(txns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for t in txns:
        name = _counterparty(t.get("description"))
        g = groups.setdefault(name.lower(), {"name": name, "count": 0, "total": 0.0, "items": []})
        g["count"] += 1
        g["total"] += _amount(t.get("amount"))
        g["items"].append(
            {
                "date": str(t.get("txn_date") or "")[:10],
                "amount": round(_amount(t.get("amount")), 2),
                # bank lines carry no user note; show the full statement description.
                "note": None,
                "label": t.get("description") or None,
            }
        )
    rows = []
    for g in groups.values():
        g["items"].sort(key=lambda it: it["date"])
        rows.append(
            {"name": g["name"], "count": g["count"], "total": round(g["total"], 2), "items": g["items"]}
        )
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


def _sent_received(txns: list[dict[str, Any]]) -> dict[str, Any]:
    """Split a set of transfers into money sent (out) vs received (in), grouped by
    counterparty, each with a per-counterparty total and a grand total."""
    sent, received = [], []
    for t in txns:
        try:
            amount = float(t.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        (sent if amount < 0 else received).append(t)
    sent_rows = _group_transfers(sent)
    received_rows = _group_transfers(received)
    return {
        "sent": sent_rows,
        "received": received_rows,
        "total_sent": round(sum(r["total"] for r in sent_rows), 2),
        "total_received": round(sum(r["total"] for r in received_rows), 2),
    }


def third_party_breakdown(bank_txns: list[dict[str, Any]]) -> dict[str, Any]:
    """Person-to-person transfers grouped by counterparty, split sent vs received.
    Own-account (Revolut) movements are excluded — see `own_movement_breakdown`."""
    return _sent_received([t for t in bank_txns if _is_transfer(t)])


def own_movement_breakdown(bank_txns: list[dict[str, Any]]) -> dict[str, Any]:
    """The user's own-account (Revolut) transfers — savings vaults, Revolut Ltd fees —
    shown separately from third parties, same sent/received shape."""
    own = [t for t in bank_txns if _is_transfer_like(t) and _is_own_movement(t)]
    return _sent_received(own)
