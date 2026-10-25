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
        _bank("b1", "DOMAIN RENEW", -15.00, "2024-09-01"),
        _bank("b2", "DOMAIN RENEW", -15.00, "2025-09-01"),
        _bank("b3", "DOMAIN RENEW", -15.00, "2026-09-01"),
    ]
    out = sub.detect_subscriptions([], bank, today=date(2026, 9, 10))
    assert len(out) == 1
    assert out[0]["cadence"] == "yearly"
    assert out[0]["annual_cost"] == 15.00


def test_stale_subscription_is_flagged():
    bank = [
        _bank("b1", "GYM PLUS", -29.00, "2026-03-02"),
        _bank("b2", "GYM PLUS", -29.00, "2026-04-02"),
        _bank("b3", "GYM PLUS", -29.00, "2026-05-02"),
    ]
    out = sub.detect_subscriptions([], bank, today=date(2026, 9, 30))  # ~4 months after last
    assert out[0]["suggested_flag"] is True


def test_card_expense_and_bank_line_counted_once():
    # Same charge appears as a card expense AND its matching bank line each month.
    expenses = [
        {"id": "e1", "source": "card", "vendor": "Adobe", "amount": 24.99, "expense_date": "2026-07-21"},
        {"id": "e2", "source": "card", "vendor": "Adobe", "amount": 24.99, "expense_date": "2026-08-21"},
        {"id": "e3", "source": "card", "vendor": "Adobe", "amount": 24.99, "expense_date": "2026-09-21"},
    ]
    bank = [
        _bank("b1", "ADOBE CREATIVE 11", -24.99, "2026-07-21"),
        _bank("b2", "ADOBE CREATIVE 22", -24.99, "2026-08-21"),
        _bank("b3", "ADOBE CREATIVE 33", -24.99, "2026-09-21"),
    ]
    out = sub.detect_subscriptions(expenses, bank, today=date(2026, 9, 30))
    assert len(out) == 1
    s = out[0]
    assert s["occurrences"] == 3          # not 6 — cross-source de-duped per date
    assert s["source"] == "mixed"
    assert s["cadence"] == "monthly"


def test_two_occurrences_is_not_a_subscription():
    # Two equal charges is a coincidence, not a recurring pattern (new ≥3 rule).
    bank = [
        _bank("b1", "NETFLIX", -13.99, "2026-08-12"),
        _bank("b2", "NETFLIX", -13.99, "2026-09-12"),
    ]
    assert sub.detect_subscriptions([], bank, today=date(2026, 9, 30)) == []


def test_topups_and_transfers_are_not_subscriptions():
    # Three equal Revolut transfers/top-ups must NOT be flagged — they're not purchases.
    bank = [
        {"id": "b1", "description": "Revolut Bank", "amount": -10.0, "txn_date": "2026-07-09", "raw": {"Type": "TRANSFER"}},
        {"id": "b2", "description": "Revolut Bank", "amount": -10.0, "txn_date": "2026-08-09", "raw": {"Type": "TRANSFER"}},
        {"id": "b3", "description": "Revolut Bank", "amount": -10.0, "txn_date": "2026-09-09", "raw": {"Type": "TRANSFER"}},
    ]
    assert sub.detect_subscriptions([], bank, today=date(2026, 9, 30)) == []


def test_subscription_charges_lists_members_with_csv_row():
    sub_row = {"vendor": "Spotify", "amount": 9.99}
    bank = [
        {"id": "b1", "description": "SPOTIFY P1", "amount": -9.99, "txn_date": "2026-07-10", "raw": {"Type": "CARD_PAYMENT", "Description": "Spotify"}},
        {"id": "b2", "description": "SPOTIFY P2", "amount": -9.99, "txn_date": "2026-08-10", "raw": {"Type": "CARD_PAYMENT"}},
        {"id": "bx", "description": "NETFLIX", "amount": -9.99, "txn_date": "2026-08-11"},  # same amount, diff brand — excluded
    ]
    expenses = [
        {"id": "e1", "source": "card", "vendor": "Spotify", "amount": 9.99, "expense_date": "2026-09-10", "category": "Entertainment"},
    ]
    out = sub.subscription_charges(sub_row, expenses, bank)
    assert len(out) == 3                                   # 2 bank + 1 card; Netflix excluded
    assert [c["source"] for c in out] == ["bank", "bank", "card"]
    assert out[0]["date"] == "2026-07-10"                  # sorted by date
    assert out[0]["raw"]["Description"] == "Spotify"       # the raw CSV row is carried through


def test_subscription_charges_excludes_topups_and_groceries():
    sub_row = {"vendor": "Continente", "amount": 4.14}
    bank = [
        {"id": "b1", "description": "Revolut Bank", "amount": -4.14, "txn_date": "2026-07-01", "raw": {"Type": "TRANSFER"}},
    ]
    expenses = [
        {"id": "e1", "source": "card", "vendor": "Continente", "amount": 4.14, "expense_date": "2026-07-06", "category": "Groceries"},
    ]
    # Transfer isn't a purchase; the grocery expense isn't a subscription candidate.
    assert sub.subscription_charges(sub_row, expenses, bank) == []


def test_grocery_category_expense_is_not_a_subscription():
    # Even three equal-amount grocery runs are one-off consumption, not a subscription.
    expenses = [
        {"id": "e1", "source": "card", "vendor": "Continente", "amount": 4.14, "expense_date": "2026-07-06", "category": "Groceries"},
        {"id": "e2", "source": "card", "vendor": "Continente", "amount": 4.14, "expense_date": "2026-08-06", "category": "Groceries"},
        {"id": "e3", "source": "card", "vendor": "Continente", "amount": 4.14, "expense_date": "2026-09-06", "category": "Groceries"},
    ]
    assert sub.detect_subscriptions(expenses, [], today=date(2026, 9, 30)) == []


def test_cash_is_never_a_subscription():
    expenses = [
        {"id": "e1", "source": "cash", "vendor": "Corner Bakery", "amount": 3.50, "expense_date": "2026-08-03"},
        {"id": "e2", "source": "cash", "vendor": "Corner Bakery", "amount": 3.50, "expense_date": "2026-09-03"},
    ]
    assert sub.detect_subscriptions(expenses, [], today=date(2026, 9, 30)) == []


def test_staleness_and_annotate():
    days, stale = sub.staleness("2026-07-02", "monthly", today=date(2026, 9, 30))
    assert days == 90 and stale is True
    days, stale = sub.staleness("2026-09-20", "monthly", today=date(2026, 9, 30))
    assert days == 10 and stale is False

    rows = [{"vendor": "Gym Plus", "cadence": "monthly", "last_seen": "2026-07-02"}]
    out = sub.annotate(rows, today=date(2026, 9, 30))
    assert out[0]["days_since_last"] == 90
    assert out[0]["stale"] is True


def test_sorted_by_annual_cost_desc():
    bank = [
        _bank("b1", "NETFLIX", -13.99, "2026-07-12"),
        _bank("b2", "NETFLIX", -13.99, "2026-08-12"),
        _bank("b3", "NETFLIX", -13.99, "2026-09-12"),
        _bank("b4", "ADOBE", -24.99, "2026-07-21"),
        _bank("b5", "ADOBE", -24.99, "2026-08-21"),
        _bank("b6", "ADOBE", -24.99, "2026-09-21"),
    ]
    out = sub.detect_subscriptions([], bank, today=date(2026, 9, 30))
    assert [s["vendor"].upper()[:5] for s in out] == ["ADOBE", "NETFL"]
