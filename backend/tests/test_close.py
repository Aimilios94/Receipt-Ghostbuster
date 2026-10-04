"""Monthly close aggregation — must reconcile to the cent. Stdlib only."""
from app.services import close


EXPENSES = [
    # September spend
    {"amount": 100.00, "category": "Groceries", "source": "card", "expense_date": "2026-09-03", "vat_amount": 13.00, "reconciled": True},
    {"amount": 50.00, "category": "Groceries", "source": "cash", "expense_date": "2026-09-05", "vat_amount": 6.50, "reconciled": False},
    {"amount": 24.00, "category": "Dining & Cafes", "source": "card", "expense_date": "2026-09-10", "vat_amount": 4.65, "reconciled": False},
    {"amount": 2000.00, "category": "Income", "source": "bank", "expense_date": "2026-09-01", "reconciled": True},
    # Different month — must be excluded
    {"amount": 999.00, "category": "Groceries", "source": "card", "expense_date": "2026-08-30", "reconciled": True},
]


def test_totals_and_income_split():
    out = close.monthly_close(EXPENSES, "2026-09")
    assert out["expense_count"] == 4               # August row excluded
    assert out["total_in"] == 2000.00
    assert out["total_out"] == 174.00              # 100 + 50 + 24
    assert out["net"] == 1826.00


def test_by_category_excludes_income():
    out = close.monthly_close(EXPENSES, "2026-09")
    assert "Income" not in out["by_category"]
    assert out["by_category"]["Groceries"] == 150.00
    assert out["by_category"]["Dining & Cafes"] == 24.00


def test_vat_owed_sums_spend_only():
    out = close.monthly_close(EXPENSES, "2026-09")
    assert out["vat_owed"] == 24.15               # 13.00 + 6.50 + 4.65


def test_cash_not_counted_unreconciled():
    out = close.monthly_close(EXPENSES, "2026-09")
    # Only the unreconciled CARD dining expense counts; cash is exempt by design.
    assert out["unreconciled_count"] == 1


BANK = [
    {"txn_date": "2026-09-01", "amount": 2500.00},   # salary in
    {"txn_date": "2026-09-02", "amount": -43.20},     # spend out
    {"txn_date": "2026-08-15", "amount": 999.00},     # different month, ignored
]


def test_bank_income_folds_into_total_in():
    # Expenses here have no Income category; income comes from the bank credit.
    expenses = [
        {"amount": 43.20, "category": "Groceries", "source": "card",
         "expense_date": "2026-09-02", "reconciled": True},
    ]
    out = close.monthly_close(expenses, "2026-09", BANK)
    assert out["bank_in"] == 2500.00
    assert out["bank_out"] == 43.20
    assert out["total_in"] == 2500.00
    assert out["net_cash_flow"] == 2456.80


def test_close_without_bank_is_backward_compatible():
    out = close.monthly_close(EXPENSES, "2026-09")   # no bank arg
    assert out["total_in"] == 2000.00                # from the Income expense row
    assert out["bank_in"] == 0.0
