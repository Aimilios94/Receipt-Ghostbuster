"""Payment-method changes, undoing a delete, and finding an expense by photo name."""
import pytest

from app.services import expense_edit


def test_card_to_cash_drops_the_bank_match():
    current = {"source": "card", "reconciled": True, "matched_transaction_id": "t1", "no_bank_match": False}
    patch, free = expense_edit.payment_change(current, "cash")
    assert patch == {"source": "cash", "reconciled": False, "matched_transaction_id": None, "no_bank_match": False}
    assert free == "t1"


def test_card_to_other_card_leaves_reconciliation():
    current = {"source": "card", "reconciled": True, "matched_transaction_id": "t1", "no_bank_match": False}
    patch, free = expense_edit.payment_change(current, "other_card")
    assert patch == {"source": "card", "reconciled": False, "matched_transaction_id": None, "no_bank_match": True}
    assert free == "t1"


def test_cash_to_card_waits_for_a_bank_line():
    patch, free = expense_edit.payment_change({"source": "cash"}, "card")
    assert patch == {"source": "card", "no_bank_match": False}
    assert free is None


def test_other_card_back_to_card():
    patch, free = expense_edit.payment_change({"source": "card", "no_bank_match": True}, "card")
    assert patch == {"source": "card", "no_bank_match": False} and free is None


def test_other_card_to_cash_clears_the_mark():
    patch, _ = expense_edit.payment_change({"source": "card", "no_bank_match": True}, "cash")
    assert patch["source"] == "cash" and patch["no_bank_match"] is False


def test_paid_with_reads_the_row():
    assert expense_edit.paid_with({"source": "cash"}) == "cash"
    assert expense_edit.paid_with({"source": "card", "no_bank_match": True}) == "other_card"
    assert expense_edit.paid_with({"source": "card"}) == "card"


def test_same_payment_changes_nothing():
    assert expense_edit.payment_change({"source": "card", "matched_transaction_id": "t1"}, "card") == ({}, None)
    assert expense_edit.payment_change({"source": "card", "no_bank_match": True}, "other_card") == ({}, None)


def test_unknown_payment_is_refused():
    with pytest.raises(ValueError):
        expense_edit.payment_change({"source": "card"}, "bank")


def test_restore_keeps_known_columns_only():
    snap = {"id": "e1", "amount": 3.5, "expense_date": "2026-09-01", "vendor": "Shop",
            "user_id": "someone-else", "not_a_column": 1, "matched_transaction_id": "t1"}
    row, lines = expense_edit.restorable(snap, [{"id": "l1", "expense_id": "e1", "amount": 3.5, "vat_rate": 6}])
    assert "user_id" not in row and "not_a_column" not in row
    assert row["id"] == "e1" and row["matched_transaction_id"] == "t1"
    assert lines == [{"description": None, "quantity": None, "unit_price": None, "amount": 3.5,
                      "vat_rate": 6, "vat_amount": None, "position": None}]


def test_restore_needs_the_core_fields():
    with pytest.raises(ValueError):
        expense_edit.restorable({"amount": 1.0, "expense_date": "2026-09-01"}, [])


def test_photo_names_prefer_the_saved_name_then_the_newest_trace():
    expenses = [
        {"id": "a", "raw_extraction": {"source_filename": "saved.jpg"}},
        {"id": "b", "raw_extraction": {}},
        {"id": "c"},
    ]
    traces = [  # newest first
        {"meta": {"expense_id": "b", "filename": "new.jpg"}},
        {"meta": {"expense_id": "b", "filename": "old.jpg"}},
        {"meta": {"expense_id": "a", "filename": "trace.jpg"}},
        {"meta": {"expense_id": "gone", "filename": "x.jpg"}},
        {"meta": {"filename": "no-expense.jpg"}},
    ]
    assert expense_edit.photo_names(expenses, traces) == {"a": "saved.jpg", "b": "new.jpg"}


def test_bank_transfer_is_stored_as_bank_and_drops_a_match():
    patch, free = expense_edit.payment_change({"source": "cash"}, "bank_transfer")
    assert patch == {"source": "bank", "reconciled": False, "matched_transaction_id": None, "no_bank_match": False}
    assert free is None
    patch, free = expense_edit.payment_change({"source": "card", "matched_transaction_id": "t1"}, "bank_transfer")
    assert patch["source"] == "bank" and free == "t1"
    assert expense_edit.paid_with({"source": "bank"}) == "bank_transfer"
