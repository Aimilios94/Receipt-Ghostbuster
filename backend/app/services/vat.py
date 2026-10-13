"""VAT math. Computed in code, never trusted to the LLM.

Convention: `amount`/`total` is the GROSS (VAT-inclusive) figure, matching how a
receipt total and a bank charge read. Given a gross total and a VAT rate (%), we
split it into net + VAT. All money is rounded to 2 decimals using bankers-safe
half-up rounding.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def _q(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def split_gross(total: float, vat_rate: float) -> dict[str, float]:
    """Split a GROSS total at `vat_rate` percent into net + vat.

    net = total / (1 + rate/100);  vat = total - net.
    A 0 (or None-as-0) rate yields vat=0, net=total.
    """
    total_d = Decimal(str(total))
    rate_d = Decimal(str(vat_rate or 0))
    if rate_d == 0:
        return {"net": float(_q(total_d)), "vat_amount": 0.0, "gross": float(_q(total_d))}
    net = total_d / (1 + rate_d / Decimal(100))
    net_q = _q(net)
    vat_q = _q(total_d - net_q)
    return {"net": float(net_q), "vat_amount": float(vat_q), "gross": float(_q(total_d))}


def vat_from_gross(total: float, vat_rate: float) -> float:
    """Just the VAT portion of a gross total."""
    return split_gross(total, vat_rate)["vat_amount"]


def line_vat(amount: float, vat_rate: float | None) -> float:
    """VAT portion of one gross line at its own rate (0/None -> 0)."""
    return split_gross(amount, vat_rate or 0)["vat_amount"]


def vat_breakdown(line_items: list[dict]) -> dict[str, Any]:
    """Sum VAT PER RATE across a receipt's line items — the per-line VAT engine.

    Each line is gross (VAT-inclusive) at its own `vat_rate`. We split every line
    in code and group the results by rate, so a single receipt with mixed rates
    (e.g. 6% + 23%) yields one bucket per rate that reconciles to the cent — no
    flattening to a dominant rate.

    Lines with no readable amount are ignored. A line with no rate is bucketed
    under rate 0.0 (treated as VAT-exempt) rather than dropped, so gross still ties
    out. Returns:
      {
        "rates": [ {"rate", "net", "vat_amount", "gross", "line_count"}, ... ],  # desc by gross
        "net", "vat_amount", "gross",   # totals
        "rate_count",                    # how many distinct rates (>0) are present
      }
    """
    # Accumulate GROSS per rate first, then split each bucket ONCE. This matches how
    # a Portuguese receipt's VAT summary is computed (VAT on the rate's net total),
    # so the breakdown reconciles to the printed figures — not per-line rounding.
    gross_by_rate: dict[Decimal, Decimal] = {}
    count_by_rate: dict[Decimal, int] = {}
    for li in line_items:
        amount = li.get("amount")
        if amount is None:
            continue
        rate = Decimal(str(li.get("vat_rate") or 0))
        gross_by_rate[rate] = gross_by_rate.get(rate, Decimal(0)) + Decimal(str(amount))
        count_by_rate[rate] = count_by_rate.get(rate, 0) + 1

    rates = []
    for rate, gross in gross_by_rate.items():
        split = split_gross(float(gross), float(rate))
        rates.append(
            {
                "rate": float(rate),
                "net": split["net"],
                "vat_amount": split["vat_amount"],
                "gross": split["gross"],
                "line_count": count_by_rate[rate],
            }
        )
    rates.sort(key=lambda r: -r["gross"])

    return {
        "rates": rates,
        "net": float(_q(sum((Decimal(str(r["net"])) for r in rates), Decimal(0)))),
        "vat_amount": float(_q(sum((Decimal(str(r["vat_amount"])) for r in rates), Decimal(0)))),
        "gross": float(_q(sum((Decimal(str(r["gross"])) for r in rates), Decimal(0)))),
        "rate_count": sum(1 for rate in gross_by_rate if rate > 0),
    }


def resolve_vat(
    total: float,
    vat_rate: float | None = None,
    vat_amount: float | None = None,
) -> dict[str, float | None]:
    """Reconcile whatever VAT info we have into a consistent (rate, amount) pair.

    - Both given: trust them, but return amounts rounded.
    - Only rate: derive amount from gross.
    - Only amount: derive the implied rate from the gross.
    - Neither: return (None, None) — VAT unknown (a missing-VAT exception candidate).
    """
    if vat_rate is not None and vat_amount is not None:
        return {"vat_rate": float(vat_rate), "vat_amount": float(_q(vat_amount))}
    if vat_rate is not None:
        return {"vat_rate": float(vat_rate), "vat_amount": vat_from_gross(total, vat_rate)}
    if vat_amount is not None:
        net = Decimal(str(total)) - Decimal(str(vat_amount))
        rate = (Decimal(str(vat_amount)) / net * Decimal(100)) if net > 0 else Decimal(0)
        return {
            "vat_rate": float(rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "vat_amount": float(_q(vat_amount)),
        }
    return {"vat_rate": None, "vat_amount": None}
