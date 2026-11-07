"""A saved monthly close: what was recorded when the month was closed, and what has
changed since. Pure, so the rules are unit-tested; the router does the reads and
writes.

Closing doesn't lock the month. It records the figures, and the close page then
says plainly if a later edit changed them, so a "closed" month can't drift quietly.
"""
from __future__ import annotations

from typing import Any

# The figures a close records and compares, with the label the page shows.
TRACKED = (
    ("total_out", "Money out"),
    ("total_in", "Money in"),
    ("vat_owed", "VAT paid"),
    ("expense_count", "Expenses"),
    ("reconciled_count", "Matched to the bank"),
    ("no_bank_line_count", "Paid with another card"),
    ("unreconciled_count", "Still unreconciled"),
)


def summary(close: dict[str, Any], exception_counts: dict[str, int]) -> dict[str, Any]:
    """The snapshot saved when a month is closed."""
    snap = {key: close.get(key) for key, _ in TRACKED}
    snap["by_category"] = dict(close.get("by_category") or {})
    snap["by_source"] = dict(close.get("by_source") or {})
    snap["exceptions"] = {k: int(v) for k, v in (exception_counts or {}).items()}
    return snap


def changes(saved: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    """Every tracked figure that differs between the saved close and the month now,
    plus categories whose total moved. An empty list means the close still holds."""
    out = []
    for key, label in TRACKED:
        if saved.get(key) != current.get(key):
            out.append({"field": key, "label": label, "saved": saved.get(key), "now": current.get(key)})
    was, now = saved.get("by_category") or {}, current.get("by_category") or {}
    for name in sorted(set(was) | set(now)):
        if was.get(name) != now.get(name):
            out.append({"field": f"category:{name}", "label": name, "saved": was.get(name), "now": now.get(name)})
    return out
