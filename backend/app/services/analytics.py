"""Analytics functions for the NL chatbot (v0.5).

Pure functions over plain dicts (expenses / bank txns / subscriptions), like
reconciliation.py and breakdown.py — so every number the chatbot reports is
**computed in code and unit-tested**, never produced by the model. The model only
selects and parameterises these functions (tool-calling); it must not do arithmetic
itself. This extends [D1] ("the AI never does the math") from extraction to Q&A.

Money is summed with Decimal and rounded to the cent. Spend excludes income and
any receipt still in the review queue (not on the ledger yet), mirroring close.py.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import breakdown as breakdown_service
from . import close as close_service
from . import subscriptions as sub_service

INCOME_CATEGORY = "Income"


def _products_of(expense: dict[str, Any]) -> list[dict[str, Any]]:
    """The named product line items the model read, from the stored raw extraction.
    (The queryable `expense_line_items` hold VAT-rate buckets, not product names —
    the real names live in `raw_extraction.line_items`.)"""
    raw = expense.get("raw_extraction") or {}
    items = raw.get("line_items") or []
    out = []
    for it in items:
        desc = (it.get("description") or "").strip()
        if not desc:
            continue
        out.append({"description": desc, "amount": it.get("amount"), "vat_rate": it.get("vat_rate")})
    return out


def _norm_product(name: str) -> str:
    """Light normalisation so repeat buys of the same product group together:
    uppercase, drop a leading VAT-class letter ("C …"/"E …" on Portuguese tills),
    collapse whitespace. Approximate — OCR product names are messy."""
    s = (name or "").upper().strip()
    s = re.sub(r"^[A-Z]\s+", "", s)   # leading single-letter VAT class
    s = re.sub(r"\s+", " ", s)
    return s


def display_product(name: str) -> str:
    """A product name without the leading VAT-class letter some tills print ("C …")."""
    return re.sub(r"^[A-Z]\s+", "", (name or "").strip())


def expense_rows(expenses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact expense rows for a card, newest first. `id` lets a row open its detail."""
    rows = [
        {
            "id": e.get("id"),
            "date": str(e.get("expense_date") or "")[:10],
            "vendor": e.get("vendor") or "Unknown",
            "category": e.get("category") or "Uncategorized",
            "amount": _q(_dec(e["amount"])),
            "vat_amount": _q(_dec(e["vat_amount"])) if e.get("vat_amount") else None,
            "source": e.get("source"),
        }
        for e in expenses
    ]
    rows.sort(key=lambda r: (r["date"], r["amount"]), reverse=True)
    return rows


def spend_rows(expenses: list[dict[str, Any]], month: str | None = None) -> list[dict[str, Any]]:
    """The rows that count as spend, for building a card's expense lists."""
    return _spend_rows(expenses, month)


def _resolve_category(expenses: list[dict[str, Any]], category: str) -> tuple[str, bool, list[str]]:
    """(the ledger's own spelling, whether it exists, every known category). The model may
    write a category in any case, and "groceries" must not silently total €0."""
    known = sorted({e.get("category") or "Uncategorized" for e in _spend_rows(expenses)})
    wanted = (category or "").strip().casefold()
    match = next((k for k in known if k.casefold() == wanted), None)
    return (match or category), match is not None, known


def category_rows(expenses: list[dict[str, Any]], category: str, month: str) -> list[dict[str, Any]]:
    """The expenses behind one category's total in a month."""
    name, _, _ = _resolve_category(expenses, category)
    return expense_rows(
        [e for e in _spend_rows(expenses, month) if (e.get("category") or "Uncategorized") == name]
    )


def vat_rows(expenses: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """The expenses behind a VAT total, for a `YYYY-MM` month or a `YYYY` year."""
    return expense_rows([
        e for e in _spend_rows(expenses)
        if e.get("vat_amount") and str(e.get("expense_date") or "")[:len(period)] == period
    ])


def product_rows(
    expenses: list[dict[str, Any]], product: str, *, vendor: str | None = None, month: str | None = None
) -> list[dict[str, Any]]:
    """The expenses whose receipt lists a product, matched the way top_products groups them."""
    key = _norm_product(product)
    return expense_rows([
        e for e in _spend_rows(expenses, month)
        if (not vendor or vendor.lower() in (e.get("vendor") or "").lower())
        and any(_norm_product(p["description"]) == key for p in _products_of(e))
    ])


def _vat_by_rate(expense: dict[str, Any], products: list[dict[str, Any]]) -> tuple[Any, list[dict[str, Any]] | None]:
    """(single rate, per-rate VAT). A mixed receipt has no single rate: the stored one is
    only its dominant rate, so it's withheld rather than reported as if it covered all."""
    tax_lines = (expense.get("raw_extraction") or {}).get("tax_lines") or []
    by_rate = [{"rate": t.get("rate"), "vat": t.get("vat")} for t in tax_lines if t.get("rate") is not None]
    rates = {r["rate"] for r in by_rate} or {p["vat_rate"] for p in products if p.get("vat_rate") is not None}
    if len(rates) > 1:
        return None, by_rate or None
    return expense.get("vat_rate"), by_rate or None


def _q(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:  # noqa: BLE001
        return Decimal(0)


def _spend_rows(expenses: list[dict[str, Any]], month: str | None = None) -> list[dict[str, Any]]:
    """Confirmed, non-income expense rows (optionally for one `YYYY-MM` month) —
    the rows that count as spend on the ledger."""
    out = []
    for e in expenses:
        if e.get("status") == "pending_review":
            continue
        if (e.get("category") or "") == INCOME_CATEGORY:
            continue
        if month and str(e.get("expense_date") or "")[:7] != month:
            continue
        out.append(e)
    return out


def total_spend(expenses: list[dict[str, Any]], month: str) -> dict[str, Any]:
    """Total spend in a `YYYY-MM` month."""
    rows = _spend_rows(expenses, month)
    total = sum((_dec(e["amount"]) for e in rows), Decimal(0))
    return {"month": month, "total": _q(total), "count": len(rows)}


def spend_by_day(
    expenses: list[dict[str, Any]], month: str, *, top: int | None = None, rank_by: str = "amount"
) -> dict[str, Any]:
    """Spend and number of expenses per day in a month: the highest- and lowest-spend
    days, the busiest day by count, and the days ranked by amount or count (`top` keeps
    the first N, with their combined total and share of the month)."""
    rows = _spend_rows(expenses, month)
    by_day: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for e in rows:
        d = str(e.get("expense_date") or "")[:10]
        by_day[d] = by_day.get(d, Decimal(0)) + _dec(e["amount"])
        counts[d] = counts.get(d, 0) + 1
    days = [{"date": d, "total": _q(v), "count": counts[d]} for d, v in sorted(by_day.items())]
    high = max(days, key=lambda x: x["total"], default=None)
    low = min(days, key=lambda x: x["total"], default=None)
    busiest = max(days, key=lambda x: (x["count"], x["total"]), default=None)
    total = sum(by_day.values(), Decimal(0))

    by_count = rank_by == "count"
    ranked = sorted(
        days,
        key=lambda x: (-x["count"], -x["total"], x["date"]) if by_count else (-x["total"], -x["count"], x["date"]),
    )
    if top:
        ranked = ranked[: max(1, int(top))]
    ranked_total = sum((by_day[x["date"]] for x in ranked), Decimal(0))
    return {
        "month": month,
        "days": days,
        "max_day": high,
        "min_day": low,
        "busiest_day": busiest,
        "ranked": {
            "by": "count" if by_count else "amount",
            "days": ranked,
            "total": _q(ranked_total),
            "share_pct": float((ranked_total / total * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if total else 0.0,
        },
        "total": _q(total),
    }


def spend_by_category(expenses: list[dict[str, Any]], month: str) -> dict[str, Any]:
    """Spend grouped by category for a month (reuses the monthly-close rollup)."""
    c = close_service.monthly_close(expenses, month)
    return {"month": month, "by_category": c["by_category"], "total": c["total_out"]}


def compare_category(
    expenses: list[dict[str, Any]], category: str, month_a: str, month_b: str
) -> dict[str, Any]:
    """Compare one category's spend between two months (a vs b). A month with no expenses
    at all has no records, which isn't the same as spending nothing, so it gets no delta."""
    category, found, known = _resolve_category(expenses, category)
    if not found:
        return {"category": category, "category_found": False, "known_categories": known,
                "month_a": month_a, "month_b": month_b}

    def cat_total(month: str) -> Decimal:
        return sum(
            (_dec(e["amount"]) for e in _spend_rows(expenses, month)
             if (e.get("category") or "Uncategorized") == category),
            Decimal(0),
        )

    a, b = cat_total(month_a), cat_total(month_b)
    a_has_data = bool(_spend_rows(expenses, month_a))
    b_has_data = bool(_spend_rows(expenses, month_b))
    both = a_has_data and b_has_data
    delta = a - b
    pct = float(delta / b * 100) if b and both else None
    return {
        "category": category,
        "category_found": True,
        "month_a": month_a, "total_a": _q(a), "month_a_has_data": a_has_data,
        "month_b": month_b, "total_b": _q(b), "month_b_has_data": b_has_data,
        "delta": _q(delta) if both else None,
        "pct_change": round(pct, 1) if pct is not None else None,
    }


def top_expenses(expenses: list[dict[str, Any]], month: str, n: int = 5) -> dict[str, Any]:
    """The n largest expenses in a month."""
    n = max(1, min(int(n or 5), 50))
    rows = sorted(_spend_rows(expenses, month), key=lambda e: abs(float(e.get("amount") or 0)), reverse=True)
    items = [
        {
            "id": e.get("id"),
            "date": str(e.get("expense_date") or "")[:10],
            "vendor": e.get("vendor") or "Unknown",
            "amount": _q(_dec(e["amount"])),
            "category": e.get("category") or "Uncategorized",
            "source": e.get("source"),
        }
        for e in rows[:n]
    ]
    return {"month": month, "n": len(items), "items": items}


def expense_details(
    expenses: list[dict[str, Any]],
    line_items_by_expense: dict[str, list[dict[str, Any]]] | None = None,
    *,
    date: str | None = None,
    vendor: str | None = None,
    month: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Full detail of specific expenses — to answer "what was that expense / what
    did I buy that day?". Filter by exact `date` (YYYY-MM-DD), `vendor` substring,
    and/or `month` (YYYY-MM). Returns vendor, category, amount, VAT, whether a
    receipt image is on file, the note, and the itemized line items."""
    line_items_by_expense = line_items_by_expense or {}
    rows = []
    for e in expenses:
        if e.get("status") == "pending_review":
            continue
        d = str(e.get("expense_date") or "")[:10]
        if date and d != date:
            continue
        if month and d[:7] != month:
            continue
        if vendor and vendor.lower() not in (e.get("vendor") or "").lower():
            continue
        rows.append(e)
    rows.sort(key=lambda e: str(e.get("expense_date") or "")[:10])
    out = []
    for e in rows[: max(1, min(int(limit or 20), 50))]:
        products = _products_of(e)
        vat_rate, vat_by_rate = _vat_by_rate(e, products)
        out.append({
            "id": e.get("id"),
            "date": str(e.get("expense_date") or "")[:10],
            "vendor": e.get("vendor") or "Unknown",
            "category": e.get("category") or "Uncategorized",
            "amount": _q(_dec(e["amount"])),
            "vat_amount": _q(_dec(e["vat_amount"])) if e.get("vat_amount") else None,
            "vat_rate": vat_rate,
            "vat_by_rate": vat_by_rate,
            "source": e.get("source"),
            "has_receipt": bool(e.get("receipt_image_url")),
            "receipt_url": e.get("receipt_image_url"),
            "note": (str(e.get("note")).strip() if e.get("note") else None),
            # The actual named products the model read (from raw extraction); empty
            # when the receipt wasn't itemized (then has_receipt lets the user check the photo).
            "products": products,
            "product_count": len(products),
        })
    return {"date": date, "vendor": vendor, "month": month, "count": len(out), "expenses": out}


def top_products(
    expenses: list[dict[str, Any]],
    *,
    vendor: str | None = None,
    month: str | None = None,
    n: int = 10,
) -> dict[str, Any]:
    """The products bought most often (by number of appearances), optionally for one
    vendor and/or month. Reads named products from the stored extraction; receipts
    that weren't itemized contribute nothing (reported as `expenses_without_items`)."""
    n = max(1, min(int(n or 10), 50))
    groups: dict[str, dict[str, Any]] = {}
    matched = 0
    without_items = 0
    for e in expenses:
        if e.get("status") == "pending_review":
            continue
        d = str(e.get("expense_date") or "")[:10]
        if month and d[:7] != month:
            continue
        if vendor and vendor.lower() not in (e.get("vendor") or "").lower():
            continue
        matched += 1
        prods = _products_of(e)
        if not prods:
            without_items += 1
        for p in prods:
            key = _norm_product(p["description"])
            if not key:
                continue
            g = groups.setdefault(key, {"product": p["description"], "count": 0, "total": 0.0})
            g["count"] += 1
            g["total"] += abs(float(p.get("amount") or 0))
    rows = [{"product": g["product"], "count": g["count"], "total": round(g["total"], 2)} for g in groups.values()]
    rows.sort(key=lambda r: (r["count"], r["total"]), reverse=True)
    return {
        "vendor": vendor, "month": month,
        "products": rows[:n],
        "expenses_considered": matched,
        "expenses_without_items": without_items,
    }


def expenses_in_range(
    expenses: list[dict[str, Any]], *, date_from: str, date_to: str
) -> dict[str, Any]:
    """All expenses between two dates (inclusive, YYYY-MM-DD), grouped by vendor with
    a per-vendor total and the individual expenses — so a long list renders grouped
    and expandable instead of one flat row per expense."""
    lo, hi = (date_from, date_to) if date_from <= date_to else (date_to, date_from)
    groups: dict[str, dict[str, Any]] = {}
    total = Decimal(0)
    count = 0
    for e in expenses:
        if e.get("status") == "pending_review":
            continue
        d = str(e.get("expense_date") or "")[:10]
        if not d or d < lo or d > hi:
            continue
        count += 1
        amt = _dec(e["amount"])
        total += amt
        vendor = (str(e.get("vendor") or "").strip()) or "Unknown"
        g = groups.setdefault(vendor.lower(), {"vendor": vendor, "count": 0, "total": Decimal(0), "items": []})
        g["count"] += 1
        g["total"] += amt
        g["items"].append({
            "id": e.get("id"),
            "date": d,
            "amount": _q(amt),
            "category": e.get("category") or "Uncategorized",
            "vat_amount": _q(_dec(e["vat_amount"])) if e.get("vat_amount") else None,
            "has_receipt": bool(e.get("receipt_image_url")),
            "receipt_url": e.get("receipt_image_url"),
        })
    group_rows = []
    for g in groups.values():
        g["items"].sort(key=lambda it: it["date"])
        group_rows.append({"vendor": g["vendor"], "count": g["count"], "total": _q(g["total"]), "items": g["items"]})
    group_rows.sort(key=lambda r: r["total"], reverse=True)
    return {"date_from": lo, "date_to": hi, "count": count, "total": _q(total), "groups": group_rows}


def bank_transactions_range(
    bank_txns: list[dict[str, Any]], *, date_from: str, date_to: str
) -> dict[str, Any]:
    """Bank-statement transactions between two dates (inclusive). Reads the stored,
    de-duplicated transactions (idempotent import, D38), so the figures are current
    regardless of which uploaded file a row came from."""
    lo, hi = (date_from, date_to) if date_from <= date_to else (date_to, date_from)
    rows = []
    total_out = Decimal(0)
    total_in = Decimal(0)
    for t in bank_txns:
        d = str(t.get("txn_date") or "")[:10]
        if not d or d < lo or d > hi:
            continue
        amt = _dec(t.get("amount"))
        if amt < 0:
            total_out += -amt
        else:
            total_in += amt
        raw = t.get("raw") or {}
        rows.append({
            "date": d,
            "description": t.get("description") or "",
            "type": str(raw.get("Type") or raw.get("type") or ""),
            "amount": _q(amt),
            "balance": _q(_dec(t.get("balance"))) if t.get("balance") is not None else None,
        })
    rows.sort(key=lambda r: r["date"])
    return {
        "date_from": lo, "date_to": hi, "count": len(rows),
        "total_out": _q(total_out), "total_in": _q(total_in), "rows": rows,
    }


def vat_paid(expenses: list[dict[str, Any]], period: str) -> dict[str, Any]:
    """Total VAT on the ledger for a period — `YYYY-MM` (a month) or `YYYY` (a year)."""
    rows = [
        e for e in expenses
        if e.get("status") != "pending_review"
        and (e.get("category") or "") != INCOME_CATEGORY
        and str(e.get("expense_date") or "")[:len(period)] == period
    ]
    vat = sum((_dec(e["vat_amount"]) for e in rows if e.get("vat_amount")), Decimal(0))
    return {"period": period, "vat": _q(vat), "count": len(rows)}


def active_subscriptions(subscriptions: list[dict[str, Any]]) -> dict[str, Any]:
    """Subscriptions the user is paying for, with their annual cost."""
    annotated = sub_service.annotate(subscriptions)
    items = [
        {
            "vendor": s.get("vendor"),
            "amount": s.get("amount"),
            "cadence": s.get("cadence"),
            "annual_cost": s.get("annual_cost"),
            "status": s.get("status") or "active",
            "stale": bool(s.get("stale")),
        }
        for s in annotated
    ]
    total_annual = sum(
        (_dec(s.get("annual_cost")) for s in annotated if (s.get("status") or "active") == "active"),
        Decimal(0),
    )
    return {"count": len(items), "total_annual": _q(total_annual), "subscriptions": items}


def subscription_candidates(
    expenses: list[dict[str, Any]],
    bank_txns: list[dict[str, Any]],
    *,
    month: str | None = None,
) -> dict[str, Any]:
    """Merchants that could be a recurring subscription — using the SAME eligibility
    rules as Refund Hunter detection ([D37]/[D23]): only non-cash card/online purchases,
    with account top-ups/transfers and one-off consumption categories (groceries, dining,
    transport, tobacco, …) excluded. Cash is NEVER a candidate. Within a single month we
    can only flag *possible* services (confirming a subscription needs ≥3 charges across
    months), so this returns candidates ranked by spend, not confirmed subscriptions."""
    charges = sub_service._collect_charges(expenses, bank_txns)
    if month:
        charges = [c for c in charges if c["date"].isoformat()[:7] == month]
    # Bank lines carry no category, so a grocery/transport bank charge (e.g. Continente,
    # Uber) would otherwise slip through. Cross-reference the user's OWN categorisations:
    # any brand they've logged under a one-off consumption category is excluded here too.
    excluded_keys = {
        sub_service.brand_key(e.get("vendor"))
        for e in expenses
        if (e.get("category") or "") in sub_service._NON_SUBSCRIPTION_CATEGORIES
    }
    excluded_keys.discard("")
    charges = [c for c in charges if c["key"] not in excluded_keys]
    groups: dict[str, dict[str, Any]] = {}
    for c in charges:
        g = groups.setdefault(c["key"], {
            "merchant": c.get("raw_vendor") or c.get("vendor") or c["key"],
            "times_charged": 0, "total": Decimal(0), "dates": [], "sources": set(),
        })
        g["times_charged"] += 1
        g["total"] += Decimal(str(c["amount"]))
        g["dates"].append(c["date"].isoformat())
        g["sources"].add(c["source"])
    rows = [
        {
            "merchant": g["merchant"],
            "times_charged": g["times_charged"],
            "total": _q(g["total"]),
            "dates": sorted(g["dates"]),
            "source": "mixed" if len(g["sources"]) > 1 else next(iter(g["sources"])),
        }
        for g in groups.values()
    ]
    rows.sort(key=lambda r: (r["times_charged"], r["total"]), reverse=True)
    return {
        "month": month,
        "candidates": rows,
        "note": "Candidates only — cash and one-off consumption (groceries, dining, etc.) are "
                "excluded. Confirming a subscription needs ≥3 same-amount charges across months.",
    }


def spend_by_vendor(
    expenses: list[dict[str, Any]], month: str | None = None, vendor: str | None = None
) -> dict[str, Any]:
    """Spend grouped by vendor (optionally for one month, or for vendors matching a name),
    highest first."""
    rows = _spend_rows(expenses, month)
    if vendor:
        rows = [e for e in rows if vendor.strip().lower() in (e.get("vendor") or "").lower()]
    vendors = [
        {"vendor": r["vendor"], "count": r["count"], "total": r["total"]}
        for r in breakdown_service.vendor_breakdown(rows)
    ]
    return {"month": month, "vendor": vendor, "vendors": vendors}


def transfers_summary(bank_txns: list[dict[str, Any]], month: str | None = None) -> dict[str, Any]:
    """Money sent to / received from third parties (people), and own-account
    (Revolut) movements, optionally for one month."""
    txns = bank_txns if not month else [t for t in bank_txns if str(t.get("txn_date") or "")[:7] == month]
    tp = breakdown_service.third_party_breakdown(txns)
    own = breakdown_service.own_movement_breakdown(txns)
    return {
        "month": month,
        "third_parties": {
            "total_sent": tp["total_sent"],
            "total_received": tp["total_received"],
            "sent": [{"name": r["name"], "total": r["total"]} for r in tp["sent"]],
            "received": [{"name": r["name"], "total": r["total"]} for r in tp["received"]],
        },
        "own_movements": {"total_sent": own["total_sent"], "total_received": own["total_received"]},
    }
