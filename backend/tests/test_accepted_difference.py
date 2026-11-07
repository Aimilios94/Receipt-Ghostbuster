"""Accepted amount differences, and flags the discrepancy check must respect."""
from app.services import exceptions, reconciliation

TXN = {"id": "t1", "txn_date": "2026-09-12", "amount": -3.60, "description": "Cafe Example", "matched_expense_id": "e1"}


def _pair(**extra):
    return {"id": "e1", "vendor": "Cafe Example", "amount": 2.10, "expense_date": "2026-09-10", "source": "card",
            "reconciled": True, "matched_transaction_id": "t1", **extra}


def test_a_linked_difference_is_an_exception_until_accepted():
    assert len(exceptions.amount_mismatch([_pair()], [TXN])) == 1
    assert exceptions.amount_mismatch([_pair(accepted_diff=1.50)], [TXN]) == []


def test_an_accepted_difference_returns_if_the_amount_changes():
    moved = {**_pair(accepted_diff=1.50), "amount": 2.00}
    assert len(exceptions.amount_mismatch([moved], [TXN])) == 1


def test_other_card_rows_and_no_receipt_lines_are_not_called_differences():
    exp = {"id": "e2", "vendor": "Food App", "amount": 18.39, "expense_date": "2026-09-13", "source": "card",
           "reconciled": False, "no_bank_match": True}
    txn = {"id": "t2", "txn_date": "2026-09-16", "amount": -16.14, "description": "Food App"}
    assert reconciliation.find_amount_discrepancies([exp], [txn]) == []
    card = {**exp, "no_bank_match": False}
    assert len(reconciliation.find_amount_discrepancies([card], [txn])) == 1
    assert reconciliation.find_amount_discrepancies([card], [{**txn, "no_receipt": True}]) == []
