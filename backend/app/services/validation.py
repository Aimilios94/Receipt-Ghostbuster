"""Deterministic guardrails on a receipt extraction (T5+).

The vision model self-reports a confidence, but it can be confidently wrong (e.g.
misreading the year). These checks run in CODE, independent of that confidence, and
decide whether an extraction is:
  - unreadable  -> don't post anything; ask the user for a clearer photo.
  - uncertain   -> post to the review queue with human-readable reasons.
  - clean       -> safe to auto-post.

This is the "AI is never trusted blindly" rule made concrete.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..models import ExtractionResult

# A receipt dated more than this many days before today is suspicious (likely a
# misread year/date). It's routed to review, not rejected.
MAX_AGE_DAYS = 60
# Allowed gap between the summed line items and the stated total.
LINE_ITEM_TOLERANCE = 0.50


def validate_receipt(
    result: ExtractionResult,
    *,
    today: date | None = None,
    confidence_threshold: float = 0.8,
) -> dict[str, Any]:
    """Return {readable, auto_post, issues}.

    - readable:  a usable amount was read (worth keeping at all).
    - auto_post: safe to post straight to the ledger (readable, confident, no issues).
    - issues:    human-readable reasons it needs a human look (shown in the UI).
    """
    today = today or date.today()
    issues: list[str] = []

    has_total = bool(result.total) and result.total > 0
    if not has_total:
        issues.append("No total amount could be read.")
    if not result.vendor:
        issues.append("The vendor name couldn't be read.")

    if result.date is None:
        issues.append("The date couldn't be read.")
    else:
        d = result.date
        if d > today:
            issues.append(f"The date reads {d.isoformat()}, which is in the future — please check.")
        else:
            age = (today - d).days
            if age > MAX_AGE_DAYS:
                issues.append(
                    f"The date reads {d.isoformat()} ({age} days ago), which looks unusually old "
                    "— confirm the year was read correctly."
                )

    if result.confidence < confidence_threshold:
        issues.append(f"The model's confidence is low ({round(result.confidence * 100)}%).")

    item_amounts = [li.amount for li in result.line_items if li.amount]
    if item_amounts and has_total:
        line_sum = round(sum(item_amounts), 2)
        if abs(line_sum - result.total) > LINE_ITEM_TOLERANCE:
            issues.append(
                f"The line items add up to {line_sum:.2f} but the total reads {result.total:.2f}."
            )

    # Readable if we at least got an amount plus one identifying field.
    readable = has_total and bool(result.vendor or result.date)
    auto_post = readable and result.confidence >= confidence_threshold and not issues

    return {"readable": readable, "auto_post": auto_post, "issues": issues}
