"""Saved monthly close: what's recorded, and what has changed since."""
from app.services import close_record

CLOSE = {"total_out": 100.0, "total_in": 0.0, "vat_owed": 9.5, "expense_count": 4, "reconciled_count": 3,
         "no_bank_line_count": 1, "unreconciled_count": 0, "by_category": {"Groceries": 60.0, "Dining & Cafes": 40.0},
         "by_source": {"card": 100.0}, "net": -100.0}


def test_summary_keeps_the_tracked_figures_and_exceptions():
    snap = close_record.summary(CLOSE, {"amount_mismatch": 0, "missing_vat": 1})
    assert snap["total_out"] == 100.0 and snap["vat_owed"] == 9.5
    assert snap["by_category"] == {"Groceries": 60.0, "Dining & Cafes": 40.0}
    assert snap["exceptions"] == {"amount_mismatch": 0, "missing_vat": 1}
    assert "net" not in snap


def test_no_changes_when_nothing_moved():
    snap = close_record.summary(CLOSE, {})
    assert close_record.changes(snap, CLOSE) == []


def test_changes_name_each_moved_figure_and_category():
    snap = close_record.summary(CLOSE, {})
    now = {**CLOSE, "total_out": 103.5, "expense_count": 5,
           "by_category": {"Groceries": 63.5, "Dining & Cafes": 40.0}}
    got = {c["field"]: (c["saved"], c["now"]) for c in close_record.changes(snap, now)}
    assert got == {"total_out": (100.0, 103.5), "expense_count": (4, 5), "category:Groceries": (60.0, 63.5)}


def test_a_new_category_counts_as_a_change():
    snap = close_record.summary(CLOSE, {})
    now = {**CLOSE, "by_category": {**CLOSE["by_category"], "Tobacco": 5.0}}
    assert [c["field"] for c in close_record.changes(snap, now)] == ["category:Tobacco"]
