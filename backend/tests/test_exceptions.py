"""Exception detection — duplicates, unmatched, mismatch, missing VAT. Stdlib only."""
from app.services import exceptions as exc


def test_cash_not_flagged_unmatched():
    expenses = [
        {"id": "1", "source": "cash", "reconciled": False},
        {"id": "2", "source": "card", "reconciled": False},
        {"id": "3", "source": "card", "reconciled": True},
    ]
    out = exc.unmatched_expenses(expenses)
    ids = {e["id"] for e in out}
    assert ids == {"2"}                    # cash excluded, reconciled excluded


def test_duplicate_detection():
    expenses = [
        {"id": "1", "vendor": "Lidl", "amount": 20.00, "expense_date": "2026-09-01"},
        {"id": "2", "vendor": "lidl", "amount": 20.00, "expense_date": "2026-09-01"},
        {"id": "3", "vendor": "Lidl", "amount": 20.00, "expense_date": "2026-09-02"},
    ]
    groups = exc.duplicates(expenses)
    assert len(groups) == 1
    assert {e["id"] for e in groups[0]} == {"1", "2"}


def test_amount_mismatch():
    expenses = [{"id": "e1", "amount": 100.00, "matched_transaction_id": "t1"}]
    bank = [{"id": "t1", "amount": -105.00}]
    out = exc.amount_mismatch(expenses, bank, amount_tolerance=0.01)
    assert len(out) == 1
    assert out[0]["difference"] == 5.00


def test_near_match_flagged_as_amount_mismatch_not_unmatched():
    # Adobe receipt 24.00 vs bank charge 24.99: same vendor + date, amount differs.
    expenses = [
        {"id": "e1", "source": "card", "vendor": "Adobe", "amount": 24.00,
         "expense_date": "2026-09-22", "reconciled": False, "input_method": "manual"},
    ]
    bank = [
        {"id": "t1", "description": "ADOBE SYSTEMS SOFTWARE", "amount": -24.99,
         "txn_date": "2026-09-22", "matched_expense_id": None},
    ]
    out = exc.collect(expenses, bank, amount_tolerance=0.01, date_window_days=3)
    assert len(out["amount_mismatch"]) == 1
    assert out["amount_mismatch"][0]["difference"] == 0.99
    # Must NOT also appear as unmatched (mutually exclusive buckets).
    assert out["unmatched_expenses"] == []
    assert out["unmatched_bank"] == []


def test_missing_vat_only_receipts():
    expenses = [
        {"id": "1", "input_method": "receipt", "vat_amount": None, "vat_rate": None},
        {"id": "2", "input_method": "receipt", "vat_amount": 4.0, "vat_rate": 24},
        {"id": "3", "input_method": "manual", "vat_amount": None, "vat_rate": None},
    ]
    out = exc.missing_vat(expenses)
    assert {e["id"] for e in out} == {"1"}   # #2 has VAT, #3 is manual
