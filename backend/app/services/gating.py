"""The receipt gate decision, in one pure place.

Given a model read (`ExtractionResult`), the deterministic `validate_receipt`
result, and the computed fields (`receipt_fields.compute`), decide whether the
receipt should **auto-post**, go to **review**, or be **rejected** — and which
guardrails fired. This is the single source of truth for gating: the `/extract`
endpoint calls it in production, and the eval harness calls the *same* function
to measure whether the guardrails actually catch bad reads (so the measured gate
is the shipped gate, not a copy).

Pure: no DB, no network. The DB-dependent duplicate check stays in the router,
which passes its message in via `duplicate_issue`.
"""
from __future__ import annotations

import datetime
from typing import Any

from ..models import ExtractionResult
from . import validation


def _vat_inconsistent(result: ExtractionResult) -> bool:
    """Self-consistency guardrail: when the model read BOTH a printed VAT table and
    item lines, their per-rate gross should agree (shown item prices are already net
    of loyalty discounts on these chains). A large mismatch means an unreliable /
    hallucinated read even if it sums to the total — don't auto-post it."""
    if not (result.tax_lines and result.line_items):
        return False

    def rate_gross(pairs) -> dict[int, float]:
        m: dict[int, float] = {}
        for rate, gross in pairs:
            if gross is None:
                continue
            key = round(float(rate or 0))
            m[key] = m.get(key, 0.0) + float(gross)
        return m

    tax_map = rate_gross(
        (tl.rate, tl.gross if tl.gross is not None else (tl.net or 0) + (tl.vat or 0))
        for tl in result.tax_lines
    )
    line_map = rate_gross((li.vat_rate, li.amount) for li in result.line_items)
    if not (tax_map and line_map):
        return False
    rates = set(tax_map) | set(line_map)
    max_div = max(abs(tax_map.get(r, 0.0) - line_map.get(r, 0.0)) for r in rates)
    return max_div > max(1.0, 0.10 * (result.total or 0.0))


def decide_gate(
    result: ExtractionResult,
    check: dict[str, Any],
    fields: dict[str, Any],
    settings: Any,
    today: datetime.date,
    *,
    year_repair: tuple[datetime.date, datetime.date] | None = None,
    duplicate_issue: str | None = None,
) -> dict[str, Any]:
    """Decide routing from the read + guardrail signals.

    `check` = validate_receipt output (readable / auto_post / issues).
    `fields` = receipt_fields.compute output (uses use_printed, breakdown, vat_amount).
    Returns gated_to ('posted'|'pending_review'|'rejected'), the full issue list,
    retake_suggested, read_reconciles, and the guardrail tags that fired.
    """
    issues = list(check.get("issues") or [])
    auto_post = bool(check.get("auto_post"))
    fired: list[str] = []

    # Unreadable -> rejected (no ledger row). Nothing else matters.
    if not check.get("readable"):
        return {
            "gated_to": "rejected",
            "auto_post": False,
            "issues": issues,
            "retake_suggested": False,
            "read_reconciles": False,
            "guardrails_fired": ["unreadable"],
            "vat_inconsistent": False,
        }

    # A repaired year is an inference, not a reading — never auto-post it.
    if year_repair is not None:
        old, new = year_repair
        issues.insert(
            0,
            f"The year looked misread — corrected {old.isoformat()} to {new.isoformat()}. "
            "Please confirm the date before posting.",
        )
        auto_post = False
        fired.append("year_repair")

    # Possible duplicate (DB-detected; message built by the caller).
    if duplicate_issue:
        issues.insert(0, duplicate_issue)
        auto_post = False
        fired.append("duplicate")

    # Estimated VAT (receipt printed none; inferred from product type) -> confirm.
    if result.vat_estimated and fields.get("vat_amount") is not None:
        issues.append(
            f"VAT isn't printed on this receipt — estimated €{fields['vat_amount']:.2f} "
            "from the product types (e.g. prepared food 13%, drinks 23%). Confirm or edit."
        )
        auto_post = False
        fired.append("estimated_vat")

    # Self-consistency (printed VAT table vs item lines).
    vat_inconsistent = _vat_inconsistent(result)
    if vat_inconsistent:
        issues.append(
            "The printed VAT table and the item lines disagree on the per-rate amounts — "
            "this read looks unreliable. Retake a flat photo, or fix the VAT lines."
        )
        auto_post = False
        fired.append("self_consistency")

    if result.confidence < settings.confidence_threshold:
        fired.append("low_confidence")

    # A read that RECONCILES to the cent (printed table trusted, or item gross ties to
    # the total) is trustworthy even at modest confidence — so low confidence ALONE
    # must not nag a retake; only a genuinely inconsistent read or a suspect date.
    breakdown = fields.get("breakdown") or {}
    rtol = max(0.10, 0.02 * (result.total or 0.0))
    read_reconciles = bool(fields.get("use_printed")) or (
        bool(result.total)
        and bool(breakdown.get("gross"))
        and abs(breakdown["gross"] - result.total) <= rtol
    )
    date_issue = year_repair is not None or (
        result.date is not None
        and (result.date > today or (today - result.date).days > validation.MAX_AGE_DAYS)
    )
    reconcile_issue = vat_inconsistent or any(
        ("add up to" in i or "VAT table totals" in i) for i in issues
    )
    retake_suggested = bool(
        reconcile_issue
        or date_issue
        or (result.confidence < settings.confidence_threshold and not read_reconciles)
    )

    return {
        "gated_to": "posted" if auto_post else "pending_review",
        "auto_post": auto_post,
        "issues": issues,
        "retake_suggested": retake_suggested,
        "read_reconciles": read_reconciles,
        "guardrails_fired": fired,
        "vat_inconsistent": vat_inconsistent,
    }
