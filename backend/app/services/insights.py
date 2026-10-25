"""Advice — rule-based, deterministic spending nudges (v0.4).

Pure functions over plain dicts, like close.py and subscriptions.py. The LLM is
NOT involved: every number is computed in code, extending D1 ("the AI never does
the math") from extraction to forward-looking advice. Three rules:

  * over_budget          — a category's month spend exceeds its budget_amount.
  * spend_up             — a category's month spend is up >= N% vs last month
                           (and above a minimum absolute delta, to mute noise on
                           tiny categories).
  * unused_subscription  — a flagged or stale subscription is still being paid.

`generate_insights` returns a list of plain dicts ready to upsert into the
`insights` table; the router persists them (preserving the user-owned `dismissed`
flag) exactly as subscriptions.detect does.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import close as close_service
from . import subscriptions as sub_service

# --- Rule thresholds (module-level constants, like subscriptions._STALE_DAYS) ---
# A category must be up at least this fraction month-over-month to nudge...
SPEND_UP_THRESHOLD = 0.25          # +25%
# ...AND up by at least this many euros, so a tiny category doesn't nudge on noise.
SPEND_UP_MIN_DELTA = 20.0
# Over budget by this ratio or more escalates the nudge from 'warning' to 'alert'.
OVER_BUDGET_ALERT_RATIO = 1.2

_SEVERITY_ORDER = {"alert": 0, "warning": 1, "info": 2}


def _q(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _prev_month(month: str) -> str:
    """'YYYY-MM' of the month before `month` ('2026-01' -> '2025-12')."""
    y, m = (int(p) for p in month.split("-")[:2])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def _spend_by_category(expenses: list[dict[str, Any]], month: str) -> dict[str, float]:
    """Per-category spend for a month, reusing the shipped close aggregation
    (confirmed-only, Income excluded, Decimal-exact)."""
    return close_service.monthly_close(expenses, month).get("by_category", {})


def generate_insights(
    expenses: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    subscriptions: list[dict[str, Any]],
    month: str,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Derive the rule-based insight rows for `month`. Pure: no DB, no clock
    unless `today` is passed through to subscription staleness."""
    actual = _spend_by_category(expenses, month)
    prev = _spend_by_category(expenses, _prev_month(month))
    out: list[dict[str, Any]] = []

    # Rule 1 — over budget -----------------------------------------------------
    budgets = {
        c["name"]: float(c["budget_amount"])
        for c in categories
        if c.get("budget_amount") is not None and c.get("name")
    }
    for cat, budget in budgets.items():
        if budget <= 0:
            continue
        spent = float(actual.get(cat, 0.0))
        if spent <= budget:
            continue
        over = _q(spent - budget)
        ratio = spent / budget if budget else 0.0
        severity = "alert" if ratio >= OVER_BUDGET_ALERT_RATIO else "warning"
        pct = round(ratio * 100)
        out.append(
            {
                "kind": "over_budget",
                "month": month,
                "subject": cat,
                "category": cat,
                "severity": severity,
                "title": f"{cat} is over budget",
                "detail": f"Spent {spent:.2f} of a {budget:.2f} budget ({pct}%).",
                "amount": over,
                "metric": {"budget": _q(budget), "actual": _q(spent), "pct": pct},
            }
        )

    # Rule 2 — spend up vs last month -----------------------------------------
    for cat, spent_now in actual.items():
        spent_now = float(spent_now)
        spent_prev = float(prev.get(cat, 0.0))
        if spent_prev <= 0:
            continue  # no baseline to compare against (new or first-month category)
        delta = spent_now - spent_prev
        if delta < SPEND_UP_MIN_DELTA:
            continue
        if spent_now < spent_prev * (1 + SPEND_UP_THRESHOLD):
            continue
        pct_change = round((delta / spent_prev) * 100)
        out.append(
            {
                "kind": "spend_up",
                "month": month,
                "subject": cat,
                "category": cat,
                "severity": "info",
                "title": f"{cat} spending is up {pct_change}%",
                "detail": f"Spent {spent_now:.2f} this month vs {spent_prev:.2f} last month.",
                "amount": _q(delta),
                "metric": {
                    "actual": _q(spent_now),
                    "prev": _q(spent_prev),
                    "pct_change": pct_change,
                },
            }
        )

    # Rule 3 — paid-but-unused subscription -----------------------------------
    for sub in sub_service.annotate(subscriptions, today):
        flagged = sub.get("status") == "flagged"
        stale = bool(sub.get("stale"))
        if not (flagged or stale):
            continue
        vendor = sub.get("vendor") or "Subscription"
        annual = float(sub.get("annual_cost") or 0.0)
        days = sub.get("days_since_last")
        reason = "flagged as unused" if flagged else f"not seen in {days} days"
        out.append(
            {
                "kind": "unused_subscription",
                "month": month,
                "subject": vendor,
                "category": None,
                "severity": "warning",
                "title": f"{vendor} — {reason}",
                "detail": (
                    f"{annual:.2f}/yr at {float(sub.get('amount') or 0.0):.2f} "
                    f"{sub.get('cadence', 'monthly')}. Cancel to stop the charge."
                ),
                "amount": _q(annual),
                "metric": {
                    "annual_cost": _q(annual),
                    "days_since_last": days,
                    "cadence": sub.get("cadence"),
                },
            }
        )

    out.sort(key=lambda r: (_SEVERITY_ORDER.get(r["severity"], 9), -(r["amount"] or 0)))
    return out
