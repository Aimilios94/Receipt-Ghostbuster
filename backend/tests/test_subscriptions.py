"""Subscription detection (Phase 2, T12). Pure logic — no DB."""
from datetime import date

from app.services import subscriptions as sub


# --- vendor normalization ---------------------------------------------------
def test_normalize_drops_reference_tokens():
    assert sub.normalize_vendor("NETFLIX.COM 4471") == "NETFLIX"
    assert sub.normalize_vendor("SPOTIFY P0A1B2") == "SPOTIFY"
    assert sub.normalize_vendor("COSMOTE TELECOM") == "COSMOTE TELECOM"


def test_normalize_handles_empty():
    assert sub.normalize_vendor(None) == ""
    assert sub.normalize_vendor("   ") == ""


def _bank(id_, desc, amount, d):
    return {"id": id_, "description": desc, "amount": amount, "txn_date": d, "matched_expense_id": None}


# --- detection --------------------------------------------------------------
def test_detects_monthly_subscription_with_annual_cost():
    bank = [
        _bank("b1", "NETFLIX.COM", -13.99, "2026-07-12"),
        _bank("b2", "NETFLIX.COM 221", -13.99, "2026-08-12"),
        _bank("b3", "NETFLIX.COM 998", -13.99, "2026-09-12"),
    ]
    out = sub.detect_subscriptions([], bank, today=date(2026, 9, 20))
    assert len(out) == 1
    s = out[0]
    assert s["vendor"].upper().startswith("NETFLIX")
    assert s["cadence"] == "monthly"
    assert s["occurrences"] == 3
    assert s["annual_cost"] == round(13.99 * 12, 2)
    assert s["suggested_flag"] is False  # last seen 8 days ago


def test_single_occurrence_is_not_a_subscription():
    bank = [_bank("b1", "ONE OFF STORE", -50.00, "2026-09-01")]
    assert sub.detect_subscriptions([], bank, today=date(2026, 9, 30)) == []


def test_income_lines_are_ignored():
    bank = [
        _bank("b1", "SALARY ACME", 2500.00, "2026-08-01"),
        _bank("b2", "SALARY ACME", 2500.00, "2026-09-01"),
    ]
    assert sub.detect_subscriptions([], bank, today=date(2026, 9, 30)) == []


def test_yearly_cadence_inferred():
    bank = [
        _bank("b1", "DOMAIN RENEW", -15.00, "2025-09-01"),
        _bank("b2", "DOMAIN RENEW", -15.00, "2026-09-01"),
    ]
    out = sub.detect_subscriptions([], bank, today=date(2026, 9, 10))
    assert len(out) == 1
    assert out[0]["cadence"] == "yearly"
    assert out[0]["annual_cost"] == 15.00


def test_stale_subscription_is_flagged():
    bank = [
        _bank("b1", "GYM PLUS", -29.00, "2026-05-02"),
        _bank("b2", "GYM PLUS", -29.00, "2026-06-02"),
    ]
    out = sub.detect_subscriptions([], bank, today=date(2026, 9, 30))  # ~4 months later
    assert out[0]["suggested_flag"] is True


def test_card_expense_and_bank_line_counted_once():
    # Same charge appears as a card expense AND its matching bank line each month.
    expenses = [
        {"id": "e1", "source": "card", "vendor": "Adobe", "amount": 24.99, "expense_date": "2026-08-21"},
        {"id": "e2", "source": "card", "vendor": "Adobe", "amount": 24.99, "expense_date": "2026-09-21"},
    ]
    bank = [
        _bank("b1", "ADOBE CREATIVE 11", -24.99, "2026-08-21"),
        _bank("b2", "ADOBE CREATIVE 22", -24.99, "2026-09-21"),
    ]
    out = sub.detect_subscriptions(expenses, bank, today=date(2026, 9, 30))
    assert len(out) == 1
    s = out[0]
    assert s["occurrences"] == 2          # not 4 — cross-source de-duped
    assert s["source"] == "mixed"
    assert s["cadence"] == "monthly"


def test_cash_is_never_a_subscription():
    expenses = [
        {"id": "e1", "source": "cash", "vendor": "Corner Bakery", "amount": 3.50, "expense_date": "2026-08-03"},
        {"id": "e2", "source": "cash", "vendor": "Corner Bakery", "amount": 3.50, "expense_date": "2026-09-03"},
    ]
    assert sub.detect_subscriptions(expenses, [], today=date(2026, 9, 30)) == []


def test_sorted_by_annual_cost_desc():
    bank = [
        _bank("b1", "NETFLIX", -13.99, "2026-08-12"),
        _bank("b2", "NETFLIX", -13.99, "2026-09-12"),
        _bank("b3", "ADOBE", -24.99, "2026-08-21"),
        _bank("b4", "ADOBE", -24.99, "2026-09-21"),
    ]
    out = sub.detect_subscriptions([], bank, today=date(2026, 9, 30))
    assert [s["vendor"].upper()[:5] for s in out] == ["ADOBE", "NETFL"]
