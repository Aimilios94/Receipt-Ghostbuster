"""Bank-transfer expenses never wait for a card line, and a receipt that prints no
VAT can be recorded as such without inventing a 0%."""
from app.services import close, exceptions, reconciliation


def test_a_bank_transfer_expense_is_not_unreconciled():
    rows = [{"amount": 10.0, "category": "Dining & Cafes", "source": "bank", "expense_date": "2026-09-12", "reconciled": False}]
    out = close.monthly_close(rows, "2026-09")
    assert out["unreconciled_count"] == 0
    assert out["total_out"] == 10.0 and out["by_source"] == {"bank": 10.0}


def test_a_bank_transfer_expense_is_never_matched_or_listed_as_unmatched():
    exp = {"id": "e1", "vendor": "Restaurant", "amount": 10.0, "expense_date": "2026-09-12", "source": "bank"}
    txn = {"id": "t1", "txn_date": "2026-09-12", "amount": -10.0, "description": "Restaurant"}
    assert reconciliation.reconcile([exp], [txn]).matches == []
    assert exceptions.unmatched_expenses([exp]) == []


def test_vat_not_shown_clears_the_missing_vat_exception():
    base = {"id": "e1", "input_method": "receipt", "vat_amount": None, "vat_rate": None}
    assert len(exceptions.missing_vat([base])) == 1
    assert exceptions.missing_vat([{**base, "vat_not_shown": True}]) == []
