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
from . import vat

# A receipt dated more than this many days before today is suspicious (likely a
# misread year/date). It's routed to review, not rejected.
MAX_AGE_DAYS = 60
# Allowed gap between the summed line items and the stated total.
LINE_ITEM_TOLERANCE = 0.50


def repair_year(d: date, today: date | None = None) -> date | None:
    """Fix an OCR year-misread deterministically (no model call, no guessing).

    The #1 extraction error on a crumpled receipt is the YEAR: the day and month
    read correctly but a "2026" is read as "2023". When a date is implausibly old
    yet the SAME month/day in the current (or last) year lands within the recent
    window, the year was almost certainly misread — snap it to that recent year.
    Returns the corrected date, or None if no confident repair applies. The caller
    still routes the result to review so a human confirms the correction.
    """
    today = today or date.today()
    if d > today or (today - d).days <= MAX_AGE_DAYS:
        return None  # not old enough to be a suspected year-misread
    for year in (today.year, today.year - 1):
        try:
            candidate = d.replace(year=year)
        except ValueError:
            continue  # e.g. Feb 29 in a non-leap year
        if candidate <= today and (today - candidate).days <= MAX_AGE_DAYS:
            return candidate
    return None


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

    # Reconciliation check. The receipt's PRINTED VAT summary table is authoritative
    # when present, so validate THAT against the total; only fall back to summing the
    # item lines (which the model may misread) when there's no usable printed table.
    printed_buckets = vat.tax_line_buckets([tl.model_dump() for tl in result.tax_lines])
    if printed_buckets and has_total:
        tax_gross = round(sum(b["amount"] for b in printed_buckets), 2)
        if abs(tax_gross - result.total) > LINE_ITEM_TOLERANCE:
            issues.append(
                f"The printed VAT table totals {tax_gross:.2f} but the total reads "
                f"{result.total:.2f} — check the VAT lines."
            )
    elif not result.discount_total:
        # Skip this check when a discount is present: the item lines are at full price
        # and legitimately sum ABOVE the amount paid, so a mismatch is expected, not a
        # misread. The amount paid (result.total) is the source of truth for the expense.
        item_amounts = [li.amount for li in result.line_items if li.amount]
        if item_amounts and has_total:
            line_sum = round(sum(item_amounts), 2)
            if abs(line_sum - result.total) > LINE_ITEM_TOLERANCE:
                issues.append(
                    f"The line items add up to {line_sum:.2f} but the total reads {result.total:.2f}."
                )

    # No VAT info at all (no summary table, no rate, no amount, no per-line rate).
    # Could be a VAT-exempt ticket (e.g. tobacco at 0%) or a misread — ask the user
    # to confirm the rate (0% if exempt) and category in review rather than guess.
    has_vat_signal = (
        result.vat_amount is not None
        or result.vat_rate is not None
        or bool(result.tax_lines)
        or any(li.vat_rate is not None for li in result.line_items)
    )
    if has_total and not has_vat_signal:
        issues.append(
            "No VAT found on this receipt — set the VAT rate (0% if exempt, e.g. tobacco) "
            "and a category before posting."
        )

    # Readable if we at least got an amount plus one identifying field.
    readable = has_total and bool(result.vendor or result.date)
    auto_post = readable and result.confidence >= confidence_threshold and not issues

    return {"readable": readable, "auto_post": auto_post, "issues": issues}
