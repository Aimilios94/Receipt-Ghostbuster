"""Editing an expense by hand: status, VAT lines and unknown VAT."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import ExpenseCreate, LineItemInput
from app.routers import expenses as router


@pytest.fixture
def store(monkeypatch):
    calls = {"updates": [], "lines": []}

    def update_expense(user_id, expense_id, patch):
        calls["updates"].append(patch)
        return {"id": expense_id, **patch} if expense_id != "missing" else {}

    def replace_line_items(user_id, expense_id, rows):
        calls["lines"].append(rows)
        return rows

    monkeypatch.setattr(router.repo, "update_expense", update_expense)
    monkeypatch.setattr(router.repo, "replace_line_items", replace_line_items)
    return calls


def _edit(body, expense_id="e1"):
    return router.edit_expense(expense_id, body, user_id="u1")["expense"]


def _confirm(body):
    return router.confirm_expense("e1", body, user_id="u1")["expense"]


def test_renaming_a_vendor_leaves_status_and_vat_alone(store):
    saved = _edit(ExpenseCreate(amount=6.71, vendor="Corner Bakery"))
    assert saved["vendor"] == "Corner Bakery"
    assert "status" not in store["updates"][0]
    assert "vat_amount" not in store["updates"][0]
    assert "vat_rate" not in store["updates"][0]
    assert store["lines"] == []


def test_edit_of_a_missing_expense_is_404(store):
    with pytest.raises(HTTPException) as exc:
        _edit(ExpenseCreate(amount=1.0, vendor="X"), expense_id="missing")
    assert exc.value.status_code == 404


def test_changed_lines_recalculate_vat_per_rate(store):
    saved = _edit(
        ExpenseCreate(
            amount=6.71,
            line_items=[
                LineItemInput(amount=1.06, vat_rate=6),
                LineItemInput(amount=5.65, vat_rate=13),
            ],
        )
    )
    assert saved["vat_amount"] == 0.71
    assert saved["vat_rate"] == 13
    assert len(store["lines"][0]) == 2


@pytest.mark.parametrize(
    "line_items",
    [[], [LineItemInput(amount=20.0, vat_rate=None)]],
    ids=["line_removed", "rate_blank"],
)
@pytest.mark.parametrize("save", [_edit, _confirm], ids=["edit", "review"])
def test_no_rate_on_any_line_saves_vat_as_unknown_not_zero(store, save, line_items):
    saved = save(ExpenseCreate(amount=20.0, line_items=line_items))
    assert saved["amount"] == 20.0
    assert saved["vat_amount"] is None
    assert saved["vat_rate"] is None
    assert store["lines"][0] == []


def test_an_explicit_zero_rate_stays_a_confirmed_zero(store):
    saved = _edit(ExpenseCreate(amount=10.0, line_items=[LineItemInput(amount=10.0, vat_rate=0)]))
    assert saved["vat_amount"] == 0
    assert saved["vat_rate"] == 0


def test_confirm_still_posts(store):
    assert _confirm(ExpenseCreate(amount=4.0, vendor="X"))["status"] == "posted"
