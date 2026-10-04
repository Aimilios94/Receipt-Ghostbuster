"""VAT math. Computed in code, never trusted to the LLM.

Convention: `amount`/`total` is the GROSS (VAT-inclusive) figure, matching how a
receipt total and a bank charge read. Given a gross total and a VAT rate (%), we
split it into net + VAT. All money is rounded to 2 decimals using bankers-safe
half-up rounding.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


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
