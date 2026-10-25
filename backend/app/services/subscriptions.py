"""Subscription detection (Phase 2, T12).

Find recurring charges — the same vendor billed the same amount on a regular
cadence — across the bank statement and the card ledger. Pure logic over plain
dicts so it is fully unit-testable, like reconciliation.py.

Approach:
  1. Build a list of outgoing *charges* from bank transactions (money out) and
     non-cash expenses. Cash is ignored (subscriptions are never cash).
  2. Normalize vendor names so "NETFLIX.COM", "NETFLIX.COM 4471" collapse to the
     same key (reference/number tokens are dropped).
  3. De-duplicate a card expense and its matching bank line (same vendor+amount
     within a couple of days) so one real charge is counted once.
  4. Group by (vendor, amount). A group seen on >= `min_occurrences` distinct
     dates is a subscription; its cadence is inferred from the median gap, and
     the annual cost is amount x periods/year.

The LLM is not involved — this is deterministic arithmetic over the ledger.
"""
from __future__ import annotations

from datetime import date
from statistics import median
from typing import Any

from . import reconciliation

# Categories of one-off consumption — a store you visit or a meal you buy, never a
# recurring *service* subscription. Two equal-amount grocery runs are a coincidence,
# not a subscription, so expenses in these categories are not subscription candidates.
_NON_SUBSCRIPTION_CATEGORIES = {
    "Groceries", "Dining & Cafes", "Transport & Fuel", "Tobacco",
    "Travel", "Health & Pharmacy", "Taxes & Fees", "Uncategorized", "Income",
}

# Tokens that are noise in bank descriptions, never a brand.
_NOISE_WORDS = {
    "POS", "PURCHASE", "PAYMENT", "PScloudMENT", "CARD", "DEBIT", "CREDIT", "VISA",
    "MASTERCARD", "TRANSACTION", "TXN", "REF", "RECURRING", "DD", "SEPA", "WWW",
    "COM", "HELP", "LTD", "INC", "THE", "GR", "EUR", "ATHENS", "GREECE",
}

# Cadence name -> (typical gap in days, charges per year).
_CADENCES = [
    ("weekly", 7, 52),
    ("monthly", 30, 12),
    ("quarterly", 91, 4),
    ("yearly", 365, 1),
]
# How stale (days since last charge) counts as "worth flagging", per cadence.
_STALE_DAYS = {"weekly": 21, "monthly": 45, "quarterly": 135, "yearly": 400, "unknown": 60}


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _vendor_tokens(name: str | None) -> list[str]:
    """Meaningful uppercase words: punctuation split out, digit-bearing
    reference tokens and generic banking noise dropped."""
    if not name:
        return []
    cleaned = name.upper()
    for ch in ".-/_,*#":
        cleaned = cleaned.replace(ch, " ")
    return [t for t in cleaned.split() if t.isalpha() and t not in _NOISE_WORDS]


def normalize_vendor(name: str | None) -> str:
    """Display-friendly brand label: the first two meaningful words.
    "SPOTIFY P0A1B2" -> "SPOTIFY", "COSMOTE TELECOM" -> "COSMOTE TELECOM"."""
    return " ".join(_vendor_tokens(name)[:2])


def brand_key(name: str | None) -> str:
    """Stable grouping key: the single leading brand word. Combined with the
    exact charge amount this merges "Adobe" with "ADOBE CREATIVE 11" while
    keeping distinct brands apart (a collision needs the same first word AND an
    identical recurring amount, which is vanishingly rare)."""
    tokens = _vendor_tokens(name)
    return tokens[0] if tokens else ""


def _display_vendor(items: list[dict[str, Any]]) -> str:
    """Prefer a real card vendor string if one exists, else the fullest
    normalized label seen for the group."""
    for it in items:
        if it.get("raw_vendor"):
            return str(it["raw_vendor"]).strip()
    labels = [it["vendor"] for it in items if it.get("vendor")]
    return (max(labels, key=len).title()) if labels else ""


def _collect_charges(
    expenses: list[dict[str, Any]], bank_txns: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    charges: list[dict[str, Any]] = []
    for t in bank_txns:
        # Only real purchases can be subscriptions. Credits, account top-ups,
        # transfers, currency exchanges and ATM withdrawals are not (reuse the same
        # classifier reconciliation uses — this is what kept "Revolut Bank"/top-ups
        # out of the subscription list, see D23).
        if not reconciliation.is_reconcilable(t) or t.get("no_receipt"):
            continue
        amount = float(t.get("amount", 0))
        charges.append(
            {
                "key": brand_key(t.get("description")),
                "vendor": normalize_vendor(t.get("description")),
                "raw_vendor": None,  # bank descriptions are noisy; prefer expense vendor
                "amount": round(abs(amount), 2),
                "date": _as_date(t["txn_date"]),
                "source": "bank",
            }
        )
    for e in expenses:
        if e.get("source") == "cash":
            continue
        # A grocery/dining/transport/etc. purchase is one-off consumption, not a
        # recurring service — skip it as a subscription candidate even if it repeats.
        if (e.get("category") or "") in _NON_SUBSCRIPTION_CATEGORIES:
            continue
        charges.append(
            {
                "key": brand_key(e.get("vendor")),
                "vendor": normalize_vendor(e.get("vendor")),
                "raw_vendor": e.get("vendor"),
                "amount": round(abs(float(e["amount"])), 2),
                "date": _as_date(e["expense_date"]),
                "source": "card",
            }
        )
    return [c for c in charges if c["key"]]


def _dedupe_cross_source(charges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge a card expense and its matching bank line into one charge."""
    out: list[dict[str, Any]] = []
    for c in sorted(charges, key=lambda x: (x["key"], x["amount"], x["date"])):
        dup = next(
            (
                o
                for o in out
                if o["key"] == c["key"]
                and abs(o["amount"] - c["amount"]) <= 0.01
                and abs((o["date"] - c["date"]).days) <= 2
            ),
            None,
        )
        if dup is not None:
            if dup["source"] != c["source"]:
                dup["source"] = "mixed"
            if not dup.get("raw_vendor") and c.get("raw_vendor"):
                dup["raw_vendor"] = c["raw_vendor"]
            continue
        out.append(dict(c))
    return out


def _infer_cadence(gaps_days: list[int]) -> tuple[str, int]:
    if not gaps_days:
        return "unknown", 0
    g = median(gaps_days)
    name, _, per_year = min(_CADENCES, key=lambda c: abs(g - c[1]))
    return name, per_year


def staleness(last_seen: Any, cadence: str, today: date | None = None) -> tuple[int, bool]:
    """Return (days since last charge, is-stale) for a cadence."""
    today = today or date.today()
    days = (today - _as_date(last_seen)).days
    return days, days > _STALE_DAYS.get(cadence, 60)


def annotate(subs: list[dict[str, Any]], today: date | None = None) -> list[dict[str, Any]]:
    """Add `days_since_last` + `stale` to stored subscription rows so the UI can
    surface "not seen in N days" without re-running detection."""
    today = today or date.today()
    out: list[dict[str, Any]] = []
    for s in subs:
        row = dict(s)
        if s.get("last_seen"):
            days, stale = staleness(s["last_seen"], s.get("cadence", "monthly"), today)
            row["days_since_last"], row["stale"] = days, stale
        else:
            row["days_since_last"], row["stale"] = None, False
        out.append(row)
    return out


def detect_subscriptions(
    expenses: list[dict[str, Any]],
    bank_txns: list[dict[str, Any]],
    *,
    today: date | None = None,
    min_occurrences: int = 3,
) -> list[dict[str, Any]]:
    """Return detected subscriptions, highest annual cost first.

    A subscription needs at least ``min_occurrences`` (default 3) charges of the
    SAME amount on distinct dates: two equal charges is a coincidence, not a
    recurring pattern, and you can't infer a cadence (or annualise it) from a
    single gap — that was the source of bogus "€10/wk × 2 → €520/yr" detections.
    """
    today = today or date.today()
    charges = _dedupe_cross_source(_collect_charges(expenses, bank_txns))

    groups: dict[tuple[str, float], list[dict[str, Any]]] = {}
    for c in charges:
        groups.setdefault((c["key"], c["amount"]), []).append(c)

    subs: list[dict[str, Any]] = []
    for (_key, amount), items in groups.items():
        dates = sorted({i["date"] for i in items})
        if len(dates) < min_occurrences:
            continue
        gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        cadence, per_year = _infer_cadence(gaps)
        sources = {i["source"] for i in items}
        source = "mixed" if len(sources) > 1 else next(iter(sources))
        days_since = (today - dates[-1]).days
        subs.append(
            {
                "vendor": _display_vendor(items),
                "amount": amount,
                "cadence": cadence,
                "annual_cost": round(amount * per_year, 2),
                "occurrences": len(dates),
                "first_seen": dates[0].isoformat(),
                "last_seen": dates[-1].isoformat(),
                "source": source,
                "days_since_last": days_since,
                "suggested_flag": days_since > _STALE_DAYS.get(cadence, 60),
            }
        )

    subs.sort(key=lambda s: s["annual_cost"], reverse=True)
    return subs


def subscription_charges(
    sub: dict[str, Any],
    expenses: list[dict[str, Any]],
    bank_txns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The individual charges behind a stored subscription — for visual confirmation.

    Re-derives (doesn't store) the bank lines and card expenses that share this
    subscription's brand + amount, using the SAME filters as detection, so the user
    can see exactly which transactions (and their raw CSV rows) drove it.
    """
    target_key = brand_key(sub.get("vendor"))
    try:
        target_amt = round(abs(float(sub.get("amount") or 0)), 2)
    except (TypeError, ValueError):
        return []
    if not target_key:
        return []

    out: list[dict[str, Any]] = []
    for t in bank_txns:
        if not reconciliation.is_reconcilable(t) or t.get("no_receipt"):
            continue
        if brand_key(t.get("description")) != target_key:
            continue
        amt = round(abs(float(t.get("amount") or 0)), 2)
        if abs(amt - target_amt) > 0.01:
            continue
        out.append(
            {
                "date": str(t.get("txn_date"))[:10],
                "label": t.get("description") or "—",
                "amount": amt,
                "source": "bank",
                "raw": t.get("raw"),            # the exact CSV row, for the snapshot
            }
        )
    for e in expenses:
        if e.get("source") == "cash":
            continue
        if (e.get("category") or "") in _NON_SUBSCRIPTION_CATEGORIES:
            continue
        if brand_key(e.get("vendor")) != target_key:
            continue
        amt = round(abs(float(e.get("amount") or 0)), 2)
        if abs(amt - target_amt) > 0.01:
            continue
        out.append(
            {
                "date": str(e.get("expense_date"))[:10],
                "label": e.get("vendor") or "—",
                "amount": amt,
                "source": "card",
                "expense_id": e.get("id"),
                "category": e.get("category"),
            }
        )
    out.sort(key=lambda c: c["date"])
    return out
