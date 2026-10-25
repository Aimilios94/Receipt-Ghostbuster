"""Chatbot analytics (v0.5) — the numbers are computed in code, so they're
provably correct over a fixed ledger regardless of the model."""
from app.services import analytics, chat as chat_service


def _expenses():
    return [
        {"expense_date": "2026-10-05", "amount": 11.58, "category": "Groceries", "vendor": "Continente", "vat_amount": 1.00, "status": "posted"},
        {"expense_date": "2026-10-05", "amount": 4.14, "category": "Groceries", "vendor": "Continente", "vat_amount": 0.30, "status": "posted"},
        {"expense_date": "2026-10-09", "amount": 18.39, "category": "Dining & Cafes", "vendor": "Uber Eats", "vat_amount": 2.00, "status": "confirmed"},
        {"expense_date": "2026-10-20", "amount": 50.00, "category": "Groceries", "vendor": "Pingo Doce", "vat_amount": 3.00, "status": "posted"},
        {"expense_date": "2026-09-15", "amount": 30.00, "category": "Groceries", "vendor": "Continente", "vat_amount": 2.00, "status": "posted"},
        {"expense_date": "2026-10-10", "amount": 1000.00, "category": "Income", "vendor": "Salary", "status": "posted"},   # income, not spend
        {"expense_date": "2026-10-11", "amount": 999.00, "category": "Groceries", "vendor": "X", "status": "pending_review"},  # not on ledger
    ]


def test_total_spend_excludes_income_and_pending():
    r = analytics.total_spend(_expenses(), "2026-10")
    assert r["total"] == 84.11 and r["count"] == 4   # 11.58 + 4.14 + 18.39 + 50.00


def test_spend_by_day_max_and_min():
    r = analytics.spend_by_day(_expenses(), "2026-10")
    assert r["max_day"] == {"date": "2026-10-20", "total": 50.00}
    assert r["min_day"] == {"date": "2026-10-05", "total": 15.72}   # 11.58 + 4.14
    assert r["total"] == 84.11
    assert [d["date"] for d in r["days"]] == ["2026-10-05", "2026-10-09", "2026-10-20"]


def test_spend_by_category():
    r = analytics.spend_by_category(_expenses(), "2026-10")
    assert r["by_category"] == {"Groceries": 65.72, "Dining & Cafes": 18.39}
    assert r["total"] == 84.11


def test_compare_category_month_over_month():
    r = analytics.compare_category(_expenses(), "Groceries", "2026-10", "2026-09")
    assert r["total_a"] == 65.72 and r["total_b"] == 30.00
    assert r["delta"] == 35.72 and r["pct_change"] == 119.1


def test_top_expenses():
    r = analytics.top_expenses(_expenses(), "2026-10", n=2)
    assert [i["amount"] for i in r["items"]] == [50.00, 18.39]
    assert r["items"][0]["vendor"] == "Pingo Doce"


def test_vat_paid_month_and_year():
    assert analytics.vat_paid(_expenses(), "2026-10")["vat"] == 6.30   # 1.00+0.30+2.00+3.00
    assert analytics.vat_paid(_expenses(), "2026")["vat"] == 8.30      # + 2.00 (Sept)


def test_spend_by_vendor_sorted_desc():
    r = analytics.spend_by_vendor(_expenses(), "2026-10")
    assert [(v["vendor"], v["total"]) for v in r["vendors"]] == [
        ("Pingo Doce", 50.00), ("Uber Eats", 18.39), ("Continente", 15.72),
    ]


def test_active_subscriptions_total_counts_active_only():
    subs = [
        {"vendor": "Netflix", "amount": 10.99, "cadence": "monthly", "annual_cost": 131.88, "status": "active", "last_seen": "2026-10-01"},
        {"vendor": "Gym", "amount": 29, "cadence": "monthly", "annual_cost": 348, "status": "cancelled", "last_seen": "2026-05-01"},
    ]
    r = analytics.active_subscriptions(subs)
    assert r["count"] == 2 and r["total_annual"] == 131.88   # cancelled excluded from the total


def _pingo(date, amount, products):
    return {
        "id": date, "expense_date": date, "amount": amount, "vendor": "Pingo Doce",
        "category": "Groceries", "vat_amount": 1.0, "vat_rate": 6, "status": "posted",
        "receipt_image_url": "https://x/r.jpg",
        "raw_extraction": {"line_items": products},
    }


def test_expense_details_shows_named_products_from_raw_extraction():
    expenses = [
        _pingo("2026-10-03", 48.24, [
            {"description": "C CREME NUTELLA 200G", "amount": 2.99, "vat_rate": 23},
            {"description": "C SUMO LARANJA 330ML", "amount": 1.99, "vat_rate": 6},
        ]),
        {"id": "x", "expense_date": "2026-10-05", "amount": 11.58, "vendor": "Continente", "status": "posted"},
    ]
    r = analytics.expense_details(expenses, {}, date="2026-10-03")
    e = r["expenses"][0]
    assert e["vendor"] == "Pingo Doce" and e["has_receipt"] is True
    assert [p["description"] for p in e["products"]] == ["C CREME NUTELLA 200G", "C SUMO LARANJA 330ML"]


def test_expense_details_no_items_still_flags_receipt():
    expenses = [{"id": "x", "expense_date": "2026-10-05", "amount": 11.58, "vendor": "Continente",
                 "status": "posted", "receipt_image_url": "u"}]
    r = analytics.expense_details(expenses, {}, vendor="contin")
    assert r["count"] == 1 and r["expenses"][0]["products"] == [] and r["expenses"][0]["has_receipt"] is True


def test_top_products_counts_across_receipts_with_normalisation():
    expenses = [
        _pingo("2026-10-03", 10, [
            {"description": "C SUMO LARANJA 330ML", "amount": 1.99, "vat_rate": 6},
            {"description": "C CREME NUTELLA 200G", "amount": 2.99, "vat_rate": 23},
        ]),
        _pingo("2026-10-10", 5, [
            {"description": "SUMO LARANJA 330ML", "amount": 1.99, "vat_rate": 6},  # same product, no leading class letter
        ]),
        # a Continente row that must be excluded by the vendor filter
        {"id": "c", "expense_date": "2026-10-04", "amount": 3, "vendor": "Continente", "status": "posted",
         "raw_extraction": {"line_items": [{"description": "C SUMO LARANJA 330ML", "amount": 1.99}]}},
    ]
    r = analytics.top_products(expenses, vendor="Pingo")
    top = r["products"][0]
    assert top["product"] == "C SUMO LARANJA 330ML" and top["count"] == 2   # normalised across the two Pingo receipts
    assert r["expenses_considered"] == 2


def test_expenses_in_range_groups_by_vendor():
    expenses = [
        {"id": "a", "expense_date": "2026-10-06", "amount": 4.18, "vendor": "MyAuchan", "category": "Groceries", "status": "posted"},
        {"id": "b", "expense_date": "2026-10-14", "amount": 4.17, "vendor": "Continente", "category": "Groceries", "status": "posted"},
        {"id": "c", "expense_date": "2026-10-15", "amount": 2.00, "vendor": "Continente", "category": "Groceries", "status": "posted"},
        {"id": "d", "expense_date": "2026-10-20", "amount": 9.99, "vendor": "Late", "status": "posted"},  # out of range
        {"id": "e", "expense_date": "2026-10-10", "amount": 99.0, "vendor": "X", "status": "pending_review"},  # excluded
    ]
    r = analytics.expenses_in_range(expenses, date_from="2026-10-05", date_to="2026-10-15")
    assert r["count"] == 3 and r["total"] == 10.35
    cont = [g for g in r["groups"] if g["vendor"] == "Continente"][0]
    assert cont["count"] == 2 and cont["total"] == 6.17
    assert [g["vendor"] for g in r["groups"]][0] == "Continente"  # highest total first


def test_expenses_in_range_handles_reversed_dates():
    expenses = [{"id": "a", "expense_date": "2026-10-06", "amount": 4.18, "vendor": "A", "status": "posted"}]
    r = analytics.expenses_in_range(expenses, date_from="2026-10-15", date_to="2026-10-05")
    assert r["count"] == 1 and r["date_from"] == "2026-10-05" and r["date_to"] == "2026-10-15"


def test_bank_transactions_range_filters_and_totals():
    bank = [
        {"txn_date": "2026-10-03", "amount": -15.98, "description": "tropsunprod.com", "raw": {"Type": "Card Payment"}, "balance": 85.85},
        {"txn_date": "2026-10-20", "amount": -3.47, "description": "Bolt", "raw": {"Type": "Card Payment"}},  # out of range
        {"txn_date": "2026-10-02", "amount": 100, "description": "Top up", "raw": {"Type": "Topup"}, "balance": 101.83},
    ]
    r = analytics.bank_transactions_range(bank, date_from="2026-10-01", date_to="2026-10-18")
    assert r["count"] == 2 and r["total_out"] == 15.98 and r["total_in"] == 100.0
    assert r["rows"][0]["date"] == "2026-10-02"  # sorted ascending


def test_attachment_builders():
    from app.services import chat as cs
    groups = cs._attachments_for("expenses_in_range", {"date_from": "2026-10-05", "date_to": "2026-10-15", "total": 10.35, "count": 3, "groups": [{"vendor": "Continente", "count": 2, "total": 6.17, "items": []}]})
    assert groups[0]["type"] == "expense_groups" and groups[0]["groups"][0]["vendor"] == "Continente"
    table = cs._attachments_for("bank_transactions", {"date_from": "2026-10-01", "date_to": "2026-10-18", "total_out": 15.98, "total_in": 100.0, "rows": [{"date": "2026-10-02", "description": "Top up", "type": "Topup", "amount": 100.0, "balance": 101.83}]})
    assert table[0]["type"] == "table" and table[0]["rows"][0][0] == "2026-10-02"
    assert table[0]["filename"] == "transactions_2026-10-01_2026-10-18.csv"


def test_subscription_candidates_excludes_cash_and_consumption():
    expenses = [
        {"expense_date": "2026-10-12", "amount": 10.0, "vendor": "Egyptian Restaurant", "category": "Dining & Cafes", "source": "cash", "status": "posted"},
        {"expense_date": "2026-10-13", "amount": 10.99, "vendor": "YouTube Premium", "category": "Software & Subscriptions", "source": "card", "status": "posted"},
        {"expense_date": "2026-10-05", "amount": 11.58, "vendor": "Continente", "category": "Groceries", "source": "card", "status": "posted"},
    ]
    bank = [
        {"txn_date": "2026-10-07", "amount": -0.83, "description": "fal.ai", "raw": {"Type": "Card Payment"}},
        {"txn_date": "2026-10-08", "amount": -3.0, "description": "Transfer to Eduardo", "raw": {"Type": "Transfer"}},  # not a purchase
    ]
    # a bank Continente line with NO category must still be excluded, because the user
    # has categorised Continente as Groceries in the ledger (cross-reference)
    bank.append({"txn_date": "2026-10-06", "amount": -4.14, "description": "Continente", "raw": {"Type": "Card Payment"}})
    r = analytics.subscription_candidates(expenses, bank)
    merchants = {c["merchant"] for c in r["candidates"]}
    assert "YouTube Premium" in merchants            # card software → candidate
    assert any("FAL" in m.upper() for m in merchants)  # online card payment → candidate
    assert "Egyptian Restaurant" not in merchants     # cash → never
    assert not any("CONTINENTE" in m.upper() for m in merchants)  # grocery bank line excluded via ledger category
    assert not any("Eduardo" in m for m in merchants)  # transfer → never


def _bank():
    return [
        {"txn_date": "2026-10-08", "amount": -500, "description": "To Piero", "raw": {"Type": "Transfer"}},
        {"txn_date": "2026-10-09", "amount": -3, "description": "Transfer to CHRISTINA", "raw": {"Type": "Transfer"}},
        {"txn_date": "2026-10-20", "amount": 10, "description": "Transfer from CHRISTINA", "raw": {"Type": "Transfer"}},
        {"txn_date": "2026-10-17", "amount": -10, "description": "Revolut Bank UAB", "raw": {"Type": "Transfer"}},
        {"txn_date": "2026-10-05", "amount": -11.58, "description": "Continente", "raw": {"Type": "Card Payment"}},
    ]


def test_transfers_summary_splits_people_vs_own():
    r = analytics.transfers_summary(_bank())
    assert r["third_parties"]["total_sent"] == 503.0      # 500 + 3 (own-Revolut excluded)
    assert r["third_parties"]["total_received"] == 10.0
    assert r["own_movements"]["total_sent"] == 10.0


# --- tool dispatch (pure, no LLM) ---

def test_expense_details_exposes_receipt_url_and_attachments():
    expenses = [_pingo("2026-10-03", 48.24, [{"description": "Milk", "amount": 1.2}])]
    r = analytics.expense_details(expenses, {}, date="2026-10-03")
    assert r["expenses"][0]["receipt_url"] == "https://x/r.jpg"
    # the chat layer turns that into a displayable attachment
    atts = chat_service._receipt_attachments(r)
    assert atts == [{"type": "receipt", "url": "https://x/r.jpg", "label": "Pingo Doce · 2026-10-03"}]


def test_receipt_attachments_skips_expenses_without_a_photo():
    r = {"expenses": [{"vendor": "X", "date": "2026-10-01", "receipt_url": None}]}
    assert chat_service._receipt_attachments(r) == []


def test_dispatch_routes_to_analytics():
    data = {"expenses": _expenses(), "bank": _bank(), "subscriptions": []}
    assert chat_service.dispatch_tool("total_spend", {"month": "2026-10"}, data)["total"] == 84.11
    assert chat_service.dispatch_tool("transfers_summary", {}, data)["third_parties"]["total_sent"] == 503.0


def test_dispatch_unknown_tool_and_missing_arg():
    data = {"expenses": _expenses(), "bank": [], "subscriptions": []}
    assert "error" in chat_service.dispatch_tool("nope", {}, data)
    assert "error" in chat_service.dispatch_tool("total_spend", {}, data)   # missing 'month'
