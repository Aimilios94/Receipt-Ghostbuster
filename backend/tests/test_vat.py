"""VAT math — the accounting-critical split. Runs with only the stdlib."""
from app.services import vat


def test_split_gross_24_percent():
    # €124.00 gross at 24% -> €100.00 net, €24.00 VAT.
    out = vat.split_gross(124.00, 24)
    assert out["net"] == 100.00
    assert out["vat_amount"] == 24.00
    assert out["gross"] == 124.00


def test_split_gross_zero_rate():
    out = vat.split_gross(50.00, 0)
    assert out["vat_amount"] == 0.0
    assert out["net"] == 50.00


def test_split_rounds_to_cents():
    # 13% on an odd total should still round cleanly and net+vat == gross.
    out = vat.split_gross(19.99, 13)
    assert round(out["net"] + out["vat_amount"], 2) == 19.99


def test_resolve_vat_rate_only():
    out = vat.resolve_vat(124.00, vat_rate=24, vat_amount=None)
    assert out["vat_rate"] == 24.0
    assert out["vat_amount"] == 24.00


def test_resolve_vat_amount_only_derives_rate():
    out = vat.resolve_vat(124.00, vat_rate=None, vat_amount=24.00)
    assert out["vat_amount"] == 24.00
    assert round(out["vat_rate"]) == 24


def test_resolve_vat_none():
    out = vat.resolve_vat(50.00, None, None)
    assert out["vat_rate"] is None
    assert out["vat_amount"] is None
