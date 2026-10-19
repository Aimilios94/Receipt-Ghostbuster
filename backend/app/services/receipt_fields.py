"""Turn an ExtractionResult into the expense fields + line items we persist.

The same accounting rules the /extract endpoint applies (printed VAT table as the
source of truth, discount scaling, per-rate VAT, net+VAT correction), factored out
so a receipt RE-SCAN can reuse them. Pure: no DB, no network.
"""
from __future__ import annotations

from typing import Any

from ..models import ExtractionResult
from . import categorization, vat


def compute(result: ExtractionResult, valid_categories: set[str] | None) -> dict[str, Any]:
    # Printed VAT summary table is authoritative when its gross ties to the total.
    # Tolerance is RELATIVE (a crumpled receipt can misread a digit, e.g. 13,31 -> 13,11)
    # so the printed table isn't dropped over a couple of cents; when it's accepted we
    # SCALE the buckets so they sum to the exact total — keeping net + VAT + total
    # internally consistent (no 37.50-vs-48.24 split).
    printed_buckets = vat.tax_line_buckets([tl.model_dump() for tl in result.tax_lines])
    printed_gross = round(sum(b["amount"] for b in printed_buckets), 2)
    total = result.total
    tol = max(0.10, 0.02 * (total or 0.0))
    use_printed = bool(printed_buckets) and (not total or abs(printed_gross - total) <= tol)

    if use_printed and total and printed_gross and abs(printed_gross - total) > 0.01:
        scale = total / printed_gross
        for b in printed_buckets:
            b["amount"] = round(b["amount"] * scale, 2)
        # push any rounding residual onto the largest bucket so they sum EXACTLY.
        diff = round(total - sum(b["amount"] for b in printed_buckets), 2)
        if diff:
            big = max(printed_buckets, key=lambda b: b["amount"])
            big["amount"] = round(big["amount"] + diff, 2)

    if use_printed:
        line_rows = [
            {
                "description": "Items",
                "quantity": None,
                "unit_price": None,
                "amount": b["amount"],
                "vat_rate": b["vat_rate"],
                "vat_amount": vat.line_vat(b["amount"], b["vat_rate"]),
                "position": idx,
            }
            for idx, b in enumerate(printed_buckets)
        ]
    else:
        line_rows = [
            {
                "description": li.description,
                "quantity": li.quantity,
                "unit_price": li.unit_price,
                "amount": li.amount,
                "vat_rate": li.vat_rate,
                "vat_amount": vat.line_vat(li.amount, li.vat_rate) if li.amount is not None else None,
                "position": idx,
            }
            for idx, li in enumerate(result.line_items)
        ]
        items_sum = round(sum(r["amount"] for r in line_rows if r["amount"] is not None), 2)
        if result.discount_total and result.total and items_sum > result.total + 0.01:
            scale = result.total / items_sum
            for r in line_rows:
                if r["amount"] is not None:
                    r["amount"] = round(r["amount"] * scale, 2)
                    r["vat_amount"] = vat.line_vat(r["amount"], r["vat_rate"])

    breakdown = vat.vat_breakdown([r for r in line_rows if r["amount"] is not None])

    if breakdown["rate_count"] > 0:
        pos_rates = [r for r in breakdown["rates"] if r["rate"] > 0]
        if pos_rates:
            dominant = max(pos_rates, key=lambda r: r["gross"])
            vat_info = {"vat_amount": breakdown["vat_amount"], "vat_rate": dominant["rate"]}
        else:
            vat_info = {"vat_amount": breakdown["vat_amount"], "vat_rate": 0}
    else:
        vat_info = vat.resolve_vat(result.total or 0.0, result.vat_rate, result.vat_amount)

    amount_paid = result.total
    g, net = breakdown["gross"], breakdown["net"]
    if g and result.total and abs(result.total - net) <= 0.05 and abs(result.total - g) > 0.05:
        amount_paid = g
    elif not amount_paid:
        amount_paid = g or printed_gross or 0.0

    category = categorization.categorize(
        result.vendor,
        None,
        llm_fallback=lambda _: result.category,
        valid_categories=valid_categories or None,
    )

    return {
        "amount": amount_paid or 0.0,
        "vat_amount": vat_info["vat_amount"],
        "vat_rate": vat_info["vat_rate"],
        "category": category,
        "line_rows": line_rows,
        # Signals the gate decision needs (see services/gating.decide_gate): whether
        # the printed VAT table was trusted, and the code-summed VAT breakdown.
        "use_printed": use_printed,
        "breakdown": breakdown,
    }
