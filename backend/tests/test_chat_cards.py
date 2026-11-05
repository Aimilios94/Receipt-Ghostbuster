"""Ask's cards: the rows come from code, and the day ranking answers count and amount."""
from app.services import analytics, chat

EXPENSES = [
    {"id": "e1", "expense_date": "2026-10-03", "amount": 48.24, "vendor": "Big Shop", "category": "Groceries", "source": "card"},
    {"id": "e2", "expense_date": "2026-10-13", "amount": 12.70, "vendor": "Kiosk", "category": "Tobacco", "source": "card"},
    {"id": "e3", "expense_date": "2026-10-13", "amount": 18.39, "vendor": "Delivery", "category": "Dining & Cafes", "source": "card"},
    {"id": "e4", "expense_date": "2026-10-13", "amount": 4.18, "vendor": "Corner Shop", "category": "Groceries", "source": "card"},
    {"id": "e5", "expense_date": "2026-10-12", "amount": 10.89, "vendor": "Big Shop", "category": "Groceries", "source": "card"},
    {"id": "e6", "expense_date": "2026-10-12", "amount": 10.00, "vendor": "Restaurant", "category": "Dining & Cafes", "source": "cash"},
    {"id": "e7", "expense_date": "2026-10-20", "amount": 99.00, "vendor": "Not Posted", "category": "Groceries", "source": "card", "status": "pending_review"},
    {"id": "e8", "expense_date": "2026-10-01", "amount": 1000.00, "vendor": "Salary", "category": "Income", "source": "card"},
    {"id": "e9", "expense_date": "2026-09-15", "amount": 30.00, "vendor": "Big Shop", "category": "Groceries", "source": "card"},
]
DATA = {"expenses": EXPENSES, "bank": [], "subscriptions": [], "line_items": {}}


def _card(tool, args):
    result = chat.dispatch_tool(tool, args, DATA)
    return result, chat._attachments_for(tool, result, DATA, args)


def test_by_day_reports_count_and_busiest_day():
    r = analytics.spend_by_day(EXPENSES, "2026-10")
    assert r["busiest_day"] == {"date": "2026-10-13", "total": 35.27, "count": 3}
    assert r["max_day"]["date"] == "2026-10-03"
    assert {"date": "2026-10-12", "total": 20.89, "count": 2} in r["days"]


def test_top_days_have_a_total_and_share_of_the_month():
    ranked = analytics.spend_by_day(EXPENSES, "2026-10", top=2)["ranked"]
    assert [d["date"] for d in ranked["days"]] == ["2026-10-03", "2026-10-13"]
    assert ranked["total"] == 83.51
    assert ranked["share_pct"] == 80.0


def test_ranking_by_count_puts_the_busiest_day_first():
    ranked = analytics.spend_by_day(EXPENSES, "2026-10", rank_by="count")["ranked"]
    assert ranked["by"] == "count"
    assert [d["date"] for d in ranked["days"]] == ["2026-10-13", "2026-10-12", "2026-10-03"]


def test_day_card_rows_and_expenses_come_from_the_ledger():
    _, [card] = _card("spend_by_day", {"month": "2026-10", "top": 3})
    assert card["type"] == "ranking"
    assert card["title"] == "Top 3 days" and card["subtitle"] == "October 2026"
    assert [r["label"] for r in card["rows"]] == ["3 Oct", "13 Oct", "12 Oct"]
    assert card["rows"][0]["bar"] == 1.0 and 0 < card["rows"][2]["bar"] < 1
    assert {e["id"] for e in card["rows"][1]["expenses"]} == {"e2", "e3", "e4"}
    assert round(sum(e["amount"] for e in card["rows"][1]["expenses"]), 2) == card["rows"][1]["total"]


def test_day_card_leaves_out_pending_and_income():
    _, [card] = _card("spend_by_day", {"month": "2026-10"})
    ids = {e["id"] for r in card["rows"] for e in r["expenses"]}
    assert "e7" not in ids and "e8" not in ids and "e9" not in ids


def test_bar_follows_count_when_ranked_by_count():
    _, [card] = _card("spend_by_day", {"month": "2026-10", "rank_by": "count"})
    assert card["rows"][0]["label"] == "13 Oct" and card["rows"][0]["bar"] == 1.0
    assert card["title"] == "Days by number of expenses"


def test_category_card():
    _, [card] = _card("spend_by_category", {"month": "2026-10"})
    assert [r["label"] for r in card["rows"]] == ["Groceries", "Dining & Cafes", "Tobacco"]
    assert card["rows"][0]["total"] == 63.31 and card["rows"][0]["count"] == 3
    assert card["total"] == 104.40


def test_vendor_card_groups_each_vendors_expenses():
    _, [card] = _card("spend_by_vendor", {"month": "2026-10"})
    big = next(r for r in card["rows"] if r["label"] == "Big Shop")
    assert big["count"] == 2 and {e["id"] for e in big["expenses"]} == {"e1", "e5"}


def test_comparison_card():
    _, [card] = _card("compare_category", {"category": "Groceries", "month_a": "2026-10", "month_b": "2026-09"})
    assert card["type"] == "comparison"
    assert (card["a"]["label"], card["a"]["total"]) == ("October 2026", 63.31)
    assert (card["b"]["label"], card["b"]["total"]) == ("September 2026", 30.0)
    assert card["delta"] == 33.31


def test_top_expenses_card_rows_can_open_their_detail():
    _, [card] = _card("top_expenses", {"month": "2026-10", "n": 2})
    assert card["type"] == "expense_list"
    assert [e["id"] for e in card["expenses"]] == ["e1", "e3"]


def test_products_show_only_for_a_single_expense_without_the_vat_letter():
    data = {**DATA, "expenses": [{**EXPENSES[0], "raw_extraction": {"line_items": [
        {"description": "C BREAD 500 G", "amount": 2.5, "vat_rate": 6},
        {"description": "E CHOCOLATE", "amount": 3.0, "vat_rate": 23},
    ]}}, EXPENSES[4]]}
    result = chat.dispatch_tool("expense_details", {"date": "2026-10-03"}, data)
    [card] = chat._attachments_for("expense_details", result, data, {"date": "2026-10-03"})
    assert [p["name"] for p in card["products"]] == ["BREAD 500 G", "CHOCOLATE"]
    assert result["expenses"][0]["product_count"] == 2
    result = chat.dispatch_tool("expense_details", {"month": "2026-10", "vendor": "Big"}, data)
    [card] = chat._attachments_for("expense_details", result, data, {})
    assert "products" not in card and len(card["expenses"]) == 2


def test_mixed_vat_receipt_has_no_single_rate():
    mixed = {**EXPENSES[0], "vat_amount": 4.47, "vat_rate": 6.0, "raw_extraction": {
        "tax_lines": [{"rate": 6.0, "vat": 1.98}, {"rate": 23.0, "vat": 2.49}]}}
    [row] = analytics.expense_details([mixed])["expenses"]
    assert row["vat_rate"] is None and row["vat_amount"] == 4.47
    assert row["vat_by_rate"] == [{"rate": 6.0, "vat": 1.98}, {"rate": 23.0, "vat": 2.49}]


def test_single_vat_receipt_keeps_its_rate():
    single = {**EXPENSES[0], "vat_amount": 2.0, "vat_rate": 13.0}
    assert analytics.expense_details([single])["expenses"][0]["vat_rate"] == 13.0


def test_several_lists_repeating_a_ranking_are_dropped():
    _, ranking = _card("spend_by_day", {"month": "2026-10", "top": 3})
    lists = [chat._attachments_for("expense_details", chat.dispatch_tool("expense_details", {"date": d}, DATA), DATA, {})[0]
             for d in ("2026-10-03", "2026-10-13", "2026-10-12")]
    kept = chat._drop_covered_lists(ranking + lists)
    assert [a["type"] for a in kept] == ["ranking"]


def test_a_list_repeating_a_ranking_is_dropped_even_alone():
    _, ranking = _card("spend_by_day", {"month": "2026-10", "rank_by": "count", "top": 1})
    repeat = chat._attachments_for("expense_details", chat.dispatch_tool("expense_details", {"date": "2026-10-13"}, DATA), DATA, {})
    assert [a["type"] for a in chat._drop_covered_lists(ranking + repeat)] == ["ranking"]


def test_a_single_receipts_products_stay_after_a_ranking():
    data = {**DATA, "expenses": [{**EXPENSES[0], "raw_extraction": {"line_items": [
        {"description": "C BREAD", "amount": 2.5, "vat_rate": 6}]}}]}
    ranking = chat._attachments_for("spend_by_day", chat.dispatch_tool("spend_by_day", {"month": "2026-10"}, data), data, {"month": "2026-10"})
    products = chat._attachments_for("expense_details", chat.dispatch_tool("expense_details", {"date": "2026-10-03"}, data), data, {})
    assert [a["type"] for a in chat._drop_covered_lists(ranking + products)] == ["ranking", "expense_list"]


def test_card_titles_read_naturally_for_one_day():
    _, [busiest] = _card("spend_by_day", {"month": "2026-10", "rank_by": "count", "top": 1})
    assert busiest["title"] == "Day with the most expenses"
    _, [top] = _card("spend_by_day", {"month": "2026-10", "top": 1})
    assert top["title"] == "Top day"


def test_failed_tool_draws_no_card():
    assert chat._attachments_for("spend_by_day", {"error": "missing argument"}, DATA, {}) == []


def test_prompt_names_the_latest_month_with_data():
    import datetime

    prompt = chat._system_prompt(datetime.date(2026, 11, 5), DATA)
    assert "(2026-10)" in prompt and "means 2026-11" in prompt


def _sum(rows, key="amount"):
    return round(sum(r[key] for r in rows), 2)


def test_comparison_months_open_to_the_expenses_behind_each_total():
    _, [card] = _card("compare_category", {"category": "Groceries", "month_a": "2026-10", "month_b": "2026-09"})
    assert {e["id"] for e in card["a"]["expenses"]} == {"e1", "e4", "e5"}
    assert _sum(card["a"]["expenses"]) == card["a"]["total"]
    assert [e["id"] for e in card["b"]["expenses"]] == ["e9"]


def test_total_spend_card_opens_to_every_expense_in_the_total():
    result, [card] = _card("total_spend", {"month": "2026-10"})
    assert card["type"] == "total" and card["total"] == result["total"]
    assert _sum(card["expenses"]) == card["total"]
    assert not {"e7", "e8", "e9"} & {e["id"] for e in card["expenses"]}


def test_vat_card_lists_the_expenses_behind_the_vat_total():
    expenses = [{**EXPENSES[0], "vat_amount": 4.47}, {**EXPENSES[1], "vat_amount": 1.53}, EXPENSES[2]]
    data = {**DATA, "expenses": expenses}
    result = chat.dispatch_tool("vat_paid", {"period": "2026-10"}, data)
    [card] = chat._attachments_for("vat_paid", result, data, {})
    assert card["total"] == 6.0 and card["amount_key"] == "vat_amount"
    assert _sum(card["expenses"], "vat_amount") == card["total"]
    assert {e["id"] for e in card["expenses"]} == {"e1", "e2"}


def test_vat_card_works_for_a_whole_year():
    data = {**DATA, "expenses": [{**EXPENSES[0], "vat_amount": 2.0}]}
    result = chat.dispatch_tool("vat_paid", {"period": "2026"}, data)
    [card] = chat._attachments_for("vat_paid", result, data, {})
    assert card["subtitle"] == "2026" and len(card["expenses"]) == 1


def test_product_rows_open_to_the_receipts_that_list_them():
    data = {**DATA, "expenses": [
        {**EXPENSES[0], "raw_extraction": {"line_items": [{"description": "C BREAD", "amount": 2.5, "vat_rate": 6}]}},
        {**EXPENSES[4], "raw_extraction": {"line_items": [{"description": "bread", "amount": 2.0, "vat_rate": 6}]}},
        {**EXPENSES[1], "raw_extraction": {"line_items": [{"description": "E MILK", "amount": 1.0, "vat_rate": 6}]}},
    ]}
    result = chat.dispatch_tool("top_products", {}, data)
    [card] = chat._attachments_for("top_products", result, data, {})
    bread = next(r for r in card["rows"] if r["label"].upper() == "BREAD")
    assert {e["id"] for e in bread["expenses"]} == {"e1", "e5"}
    assert card["count_unit"] == "times"


def test_people_rows_open_to_their_transfers():
    bank = [
        {"txn_date": "2026-10-02", "amount": -5.0, "description": "Transfer to ALEX EXAMPLE", "raw": {"Type": "Transfer"}},
        {"txn_date": "2026-10-03", "amount": -2.0, "description": "Revolut Ltd", "raw": {"Type": "Transfer", "Counterparty": "ALEX EXAMPLE"}},
        {"txn_date": "2026-09-03", "amount": -9.0, "description": "Transfer to ALEX EXAMPLE", "raw": {"Type": "Transfer"}},
    ]
    data = {**DATA, "bank": bank}
    result = chat.dispatch_tool("transfers_summary", {"month": "2026-10"}, data)
    [card] = chat._attachments_for("transfers_summary", result, data, {})
    assert card["total"] == 7.0 and card["count_unit"] == "transfers"
    [row] = card["rows"]
    assert row["count"] == 2 and _sum(row["transactions"]) == row["total"]


def test_a_total_card_beside_a_ranking_is_dropped():
    total = chat._attachments_for("total_spend", chat.dispatch_tool("total_spend", {"month": "2026-10"}, DATA), DATA, {})
    _, ranking = _card("spend_by_category", {"month": "2026-10"})
    assert [a["type"] for a in chat._drop_covered_lists(total + ranking)] == ["ranking"]
    assert [a["type"] for a in chat._drop_covered_lists(total)] == ["total"]


def test_range_list_items_can_open_their_detail():
    r = analytics.expenses_in_range(EXPENSES, date_from="2026-10-12", date_to="2026-10-13")
    assert {it["id"] for g in r["groups"] for it in g["items"]} == {"e2", "e3", "e4", "e5", "e6"}


def test_a_category_in_any_case_finds_the_real_total():
    for spelling in ("groceries", "GROCERIES", " Groceries "):
        r = analytics.compare_category(EXPENSES, spelling, "2026-10", "2026-09")
        assert r["category"] == "Groceries" and r["category_found"] is True
        assert r["total_a"] == 63.31 and r["total_b"] == 30.0


def test_card_rows_match_a_category_in_any_case():
    _, [card] = _card("compare_category", {"category": "groceries", "month_a": "2026-10", "month_b": "2026-09"})
    assert card["title"] == "Groceries" and card["a"]["total"] == 63.31
    assert round(sum(e["amount"] for e in card["a"]["expenses"]), 2) == 63.31


def test_an_unknown_category_is_not_found_rather_than_zero():
    r, cards = _card("compare_category", {"category": "Pets", "month_a": "2026-10", "month_b": "2026-09"})
    assert r["category_found"] is False and "total_a" not in r
    assert "Groceries" in r["known_categories"] and cards == []


def test_a_question_about_one_vendor_shows_only_that_vendor():
    result, [card] = _card("spend_by_vendor", {"month": "2026-10", "vendor": "big shop"})
    assert [v["vendor"] for v in result["vendors"]] == ["Big Shop"]
    assert card["title"] == "Spending at Big Shop"
    assert [r["label"] for r in card["rows"]] == ["Big Shop"]
    assert card["total"] == 59.13 and {e["id"] for e in card["rows"][0]["expenses"]} == {"e1", "e5"}


def test_without_a_vendor_every_vendor_is_listed():
    _, [card] = _card("spend_by_vendor", {"month": "2026-10"})
    assert card["title"] == "Spending by vendor" and len(card["rows"]) == 5
