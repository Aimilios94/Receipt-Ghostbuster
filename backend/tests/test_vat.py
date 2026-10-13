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


# --- Per-line VAT (mixed-rate receipts) ------------------------------------
def test_line_vat_single_line():
    # €12.30 gross at 23% -> €2.30 VAT.
    assert vat.line_vat(12.30, 23) == 2.30
    assert vat.line_vat(10.00, None) == 0.0
    assert vat.line_vat(10.00, 0) == 0.0


def test_vat_breakdown_mixed_rates_sums_per_rate():
    # One receipt, two rates: 6% food + 23% other. VAT summed PER RATE in code.
    lines = [
        {"amount": 2.12, "vat_rate": 6},    # net 2.00, vat 0.12
        {"amount": 10.18, "vat_rate": 23},  # net 8.28, vat 1.90
    ]
    bd = vat.vat_breakdown(lines)
    assert bd["rate_count"] == 2
    # Sorted by gross desc -> 23% first.
    assert [r["rate"] for r in bd["rates"]] == [23.0, 6.0]
    by_rate = {r["rate"]: r for r in bd["rates"]}
    assert by_rate[6.0]["vat_amount"] == 0.12
    assert by_rate[23.0]["vat_amount"] == 1.90
    # Totals reconcile to the cent: gross == sum of lines, net + vat == gross.
    assert bd["gross"] == 12.30
    assert bd["vat_amount"] == 2.02
    assert round(bd["net"] + bd["vat_amount"], 2) == bd["gross"]


def test_vat_breakdown_groups_same_rate_lines():
    lines = [
        {"amount": 5.00, "vat_rate": 23},
        {"amount": 7.00, "vat_rate": 23},
    ]
    bd = vat.vat_breakdown(lines)
    assert bd["rate_count"] == 1
    assert bd["rates"][0]["line_count"] == 2
    assert bd["rates"][0]["gross"] == 12.00


def test_vat_breakdown_no_rate_bucketed_as_exempt():
    # A line with no rate still ties out in gross (bucketed at 0%, no VAT).
    bd = vat.vat_breakdown([{"amount": 9.99, "vat_rate": None}])
    assert bd["rate_count"] == 0
    assert bd["vat_amount"] == 0.0
    assert bd["gross"] == 9.99


def test_vat_breakdown_bucket_rounding_matches_receipt():
    # VAT is computed on the rate's GROSS total (bucket-first), not summed per line.
    # Continente 13% bucket: 2.67 + 3.09 = 5.76 -> VAT 0.66 (per-line rounding gives 0.67).
    bd = vat.vat_breakdown(
        [{"amount": 2.67, "vat_rate": 13}, {"amount": 3.09, "vat_rate": 13}]
    )
    assert bd["rates"][0]["gross"] == 5.76
    assert bd["rates"][0]["vat_amount"] == 0.66


def test_vat_breakdown_real_continente_three_rates():
    # The real 1000017708.jpg receipt: 6% + 13% + 23% -> total VAT 1.00, gross 11.58,
    # matching the printed IVA summary (A 0.32, B 0.66, C 0.02).
    lines = [
        {"amount": 2.24, "vat_rate": 6},
        {"amount": 1.49, "vat_rate": 6},
        {"amount": 1.99, "vat_rate": 6},
        {"amount": 2.67, "vat_rate": 13},
        {"amount": 3.09, "vat_rate": 13},
        {"amount": 0.10, "vat_rate": 23},
    ]
    bd = vat.vat_breakdown(lines)
    by_rate = {r["rate"]: r["vat_amount"] for r in bd["rates"]}
    assert by_rate[6.0] == 0.32
    assert by_rate[13.0] == 0.66
    assert by_rate[23.0] == 0.02
    assert bd["vat_amount"] == 1.00
    assert bd["gross"] == 11.58


def test_vat_breakdown_empty():
    bd = vat.vat_breakdown([])
    assert bd["rates"] == []
    assert bd["vat_amount"] == 0.0
    assert bd["rate_count"] == 0
