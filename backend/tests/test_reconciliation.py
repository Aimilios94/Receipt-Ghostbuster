"""Reconciliation matching. Requires rapidfuzz (pip install -r requirements.txt)."""
from app.services import reconciliation as rec


def test_matches_on_amount_date_vendor():
    expenses = [
        {"id": "e1", "source": "card", "vendor": "Starbucks", "amount": 4.50, "expense_date": "2026-09-10", "reconciled": False},
    ]
    bank = [
        {"id": "t1", "description": "STARBUCKS COFFEE ATHENS", "amount": -4.50, "txn_date": "2026-09-10", "matched_expense_id": None},
    ]
    out = rec.reconcile(expenses, bank)
    assert len(out.matches) == 1
    assert out.matches[0]["expense_id"] == "e1"
    assert out.matches[0]["transaction_id"] == "t1"


def test_cash_is_skipped():
    expenses = [
        {"id": "e1", "source": "cash", "vendor": "Kiosk", "amount": 4.50, "expense_date": "2026-09-10", "reconciled": False},
    ]
    bank = [
        {"id": "t1", "description": "KIOSK", "amount": -4.50, "txn_date": "2026-09-10", "matched_expense_id": None},
    ]
    out = rec.reconcile(expenses, bank)
    assert out.matches == []


def test_amount_out_of_tolerance_no_match():
    expenses = [
        {"id": "e1", "source": "card", "vendor": "Lidl", "amount": 20.00, "expense_date": "2026-09-10", "reconciled": False},
    ]
    bank = [
        {"id": "t1", "description": "LIDL", "amount": -25.00, "txn_date": "2026-09-10", "matched_expense_id": None},
    ]
    out = rec.reconcile(expenses, bank, amount_tolerance=0.01)
    assert out.matches == []


def test_date_outside_window_no_match():
    expenses = [
        {"id": "e1", "source": "card", "vendor": "Lidl", "amount": 20.00, "expense_date": "2026-09-01", "reconciled": False},
    ]
    bank = [
        {"id": "t1", "description": "LIDL", "amount": -20.00, "txn_date": "2026-09-20", "matched_expense_id": None},
    ]
    out = rec.reconcile(expenses, bank, date_window_days=3)
    assert out.matches == []


def test_one_to_one_no_double_matching():
    # Two identical expenses, one bank txn -> only one should match.
    expenses = [
        {"id": "e1", "source": "card", "vendor": "Lidl", "amount": 20.00, "expense_date": "2026-09-10", "reconciled": False},
        {"id": "e2", "source": "card", "vendor": "Lidl", "amount": 20.00, "expense_date": "2026-09-10", "reconciled": False},
    ]
    bank = [
        {"id": "t1", "description": "LIDL", "amount": -20.00, "txn_date": "2026-09-10", "matched_expense_id": None},
    ]
    out = rec.reconcile(expenses, bank)
    assert len(out.matches) == 1
    assert len(out.matched_transaction_ids) == 1
