"""Monthly close aggregation — the automated personal month-end.

Pure function over expense dicts. Sign convention for the ledger:
  - 'Income' category counts as money IN.
  - Everything else counts as money OUT (spend).
All figures computed in code (Decimal) so they reconcile to the cent.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

INCOME_CATEGORY = "Income"


def _q(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _in_month(expense_date: Any, month: str) -> bool:
    """month is 'YYYY-MM'."""
    return str(expense_date)[:7] == month


def monthly_close(
    expenses: list[dict[str, Any]],
    month: str,
    bank_transactions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Roll up the month.

    Spend, VAT, and category breakdown come from the EXPENSE ledger (itemized,
    VAT-aware). Income and the cash-flow view come from the BANK (actual money in/
    out), plus any expenses explicitly categorized as Income. `total_in` therefore
    reflects real receipts (e.g. salary) even when there is no receipt to log.
    """
    rows = [e for e in expenses if _in_month(e.get("expense_date"), month)]

    income_expenses = Decimal(0)
    total_out = Decimal(0)
    vat_owed = Decimal(0)
    by_category: dict[str, Decimal] = {}
    by_source: dict[str, Decimal] = {}
    unreconciled = 0

    for e in rows:
        amount = Decimal(str(e["amount"]))
        category = e.get("category") or "Uncategorized"
        source = e.get("source") or "unknown"

        if category == INCOME_CATEGORY:
            income_expenses += amount
        else:
            total_out += amount
            by_category[category] = by_category.get(category, Decimal(0)) + amount
            by_source[source] = by_source.get(source, Decimal(0)) + amount
            if e.get("vat_amount"):
                vat_owed += Decimal(str(e["vat_amount"]))

        # Cash is never expected to reconcile; don't count it as unreconciled.
        if e.get("source") != "cash" and not e.get("reconciled"):
            unreconciled += 1

    # Cash-flow view from the bank statement.
    bank_in = Decimal(0)
    bank_out = Decimal(0)
    for t in bank_transactions or []:
        if not _in_month(t.get("txn_date"), month):
            continue
        amt = Decimal(str(t["amount"]))
        if amt >= 0:
            bank_in += amt
        else:
            bank_out += -amt

    total_in = income_expenses + bank_in

    return {
        "month": month,
        "expense_count": len(rows),
        "total_in": _q(total_in),
        "total_out": _q(total_out),
        "net": _q(total_in - total_out),
        "vat_owed": _q(vat_owed),
        "by_category": {k: _q(v) for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])},
        "by_source": {k: _q(v) for k, v in by_source.items()},
        "bank_in": _q(bank_in),
        "bank_out": _q(bank_out),
        "net_cash_flow": _q(bank_in - bank_out),
        "unreconciled_count": unreconciled,
    }
