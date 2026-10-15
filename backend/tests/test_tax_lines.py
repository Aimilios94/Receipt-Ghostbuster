"""Printed VAT/IVA summary table as the VAT source of truth.

Regression for the Continente 1000017808 receipt: the model misread the item
lines (summed 2.98 vs the real 4.17) and guessed VAT (0.09/0.26). The printed IVA
table (6% -> 0.15, 23% -> 0.30) is transcribed and trusted instead.
"""
from datetime import date

from app.models import ExtractionResult, LineItem, TaxLine
from app.services import validation as v
from app.services import vat

# The real printed IVA summary table on receipt 1000017808.
REAL_TAX = [
    {"rate": 6, "net": 2.44, "vat": 0.15, "gross": 2.59},
    {"rate": 23, "net": 1.28, "vat": 0.30, "gross": 1.58},
]


def test_buckets_reproduce_printed_vat_to_the_cent():
    buckets = vat.tax_line_buckets(REAL_TAX)
    bd = vat.vat_breakdown(buckets)
    by_rate = {r["rate"]: r for r in bd["rates"]}
    assert by_rate[6.0]["vat_amount"] == 0.15
    assert by_rate[23.0]["vat_amount"] == 0.30
    assert bd["vat_amount"] == 0.45
    assert bd["gross"] == 4.17


def test_gross_derived_from_net_plus_vat_when_total_missing():
    buckets = vat.tax_line_buckets([{"rate": 23, "net": 1.28, "vat": 0.30, "gross": None}])
    assert buckets == [{"rate": 23.0, "amount": 1.58, "vat_rate": 23.0}]


def test_unusable_rows_are_dropped():
    # No rate, or no way to resolve a gross -> dropped (never guessed).
    buckets = vat.tax_line_buckets(
        [{"rate": None, "gross": 5.0}, {"rate": 13, "net": None, "vat": None, "gross": None}]
    )
    assert buckets == []


def _res(**kw):
    base = dict(vendor="Continente", date=date(2026, 10, 14), total=4.17, confidence=0.95)
    base.update(kw)
    return ExtractionResult(**base)


def test_printed_table_tying_to_total_is_not_flagged():
    # Item lines the model misread (sum 2.98) must NOT trigger a mismatch when the
    # printed VAT table reconciles to the total.
    res = _res(
        line_items=[LineItem(amount=1.40, vat_rate=6), LineItem(amount=1.58, vat_rate=23)],
        tax_lines=[TaxLine(**t) for t in REAL_TAX],
    )
    out = v.validate_receipt(res, today=date(2026, 10, 15))
    assert not any("add up to" in i or "VAT table totals" in i for i in out["issues"])


def test_printed_table_not_tying_to_total_is_flagged():
    res = _res(tax_lines=[TaxLine(rate=6, gross=1.00), TaxLine(rate=23, gross=1.00)])
    out = v.validate_receipt(res, today=date(2026, 10, 15))
    assert any("printed VAT table totals" in i for i in out["issues"])


def test_falls_back_to_line_item_check_without_a_table():
    res = _res(line_items=[LineItem(amount=1.00, vat_rate=6)])  # 1.00 vs 4.17
    out = v.validate_receipt(res, today=date(2026, 10, 15))
    assert any("line items add up to" in i for i in out["issues"])
