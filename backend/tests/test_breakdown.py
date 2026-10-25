"""Spending breakdown — by vendor, and third-party transfers (sent/received)."""
from app.services import breakdown as bd


def test_vendor_breakdown_groups_and_totals_desc():
    expenses = [
        {"vendor": "Continente", "amount": -11.58},
        {"vendor": "Continente", "amount": -4.14},
        {"vendor": "Bolt", "amount": -3.47},
        {"vendor": "continente", "amount": -4.48},  # case-insensitive merge
    ]
    rows = bd.vendor_breakdown(expenses)
    assert rows[0]["vendor"] == "Continente"
    assert rows[0]["count"] == 3 and rows[0]["total"] == 20.20
    assert rows[1]["vendor"] == "Bolt" and rows[1]["total"] == 3.47
    # highest total first
    assert [r["total"] for r in rows] == sorted((r["total"] for r in rows), reverse=True)


def test_vendor_breakdown_items_carry_date_amount_note():
    expenses = [
        {"vendor": "Continente", "amount": -11.58, "expense_date": "2026-10-05",
         "note": "weekly shop", "category": "Groceries"},
        {"vendor": "Continente", "amount": -4.14, "expense_date": "2026-10-06"},
    ]
    rows = bd.vendor_breakdown(expenses)
    items = rows[0]["items"]
    assert [it["date"] for it in items] == ["2026-10-05", "2026-10-06"]  # sorted by date
    assert items[0]["amount"] == 11.58 and items[0]["note"] == "weekly shop"
    assert items[0]["category"] == "Groceries"
    assert items[1]["note"] is None


def test_transfer_items_carry_date_amount_and_label():
    txns = [
        _transfer("Transfer to CHRISTINA", -2.72),
        _transfer("Transfer to CHRISTINA", -2.0),
    ]
    tp = bd.third_party_breakdown(txns)
    items = tp["sent"][0]["items"]
    assert len(items) == 2
    assert {it["amount"] for it in items} == {2.72, 2.0}
    assert all(it["label"] == "Transfer to CHRISTINA" for it in items)


def test_vendor_breakdown_blank_vendor_is_unknown():
    rows = bd.vendor_breakdown([{"vendor": "", "amount": -5}, {"amount": -2}])
    assert len(rows) == 1 and rows[0]["vendor"] == "Unknown" and rows[0]["total"] == 7.0


def _transfer(desc, amount, ttype="Transfer"):
    return {"description": desc, "amount": amount, "raw": {"Type": ttype}}


def test_third_party_split_sent_received_with_totals():
    txns = [
        _transfer("To Eduardo Eduardo", -3),
        _transfer("Transfer to CHRISTINA IFIGENEIA", -2.72),
        _transfer("Transfer to CHRISTINA IFIGENEIA", -2.0),
        _transfer("Transfer from CHRISTINA IFIGENEIA", 10),
        # a card purchase and a top-up must be ignored
        {"description": "Continente", "amount": -11.58, "raw": {"Type": "Card Payment"}},
        {"description": "Google Pay top-up by *6517", "amount": 100, "raw": {"Type": "Topup"}},
    ]
    tp = bd.third_party_breakdown(txns)
    sent_names = {r["name"]: r for r in tp["sent"]}
    assert "Eduardo Eduardo" in sent_names
    # the two Christina sends merge: 2.72 + 2.00
    assert sent_names["CHRISTINA IFIGENEIA"]["count"] == 2
    assert sent_names["CHRISTINA IFIGENEIA"]["total"] == 4.72
    assert tp["total_sent"] == 7.72          # 3 + 4.72
    assert tp["received"][0]["name"] == "CHRISTINA IFIGENEIA"
    assert tp["total_received"] == 10.0


def test_third_party_detects_transfer_from_description_without_type():
    txns = [{"description": "Transfer to Someone", "amount": -5}]  # no raw Type
    tp = bd.third_party_breakdown(txns)
    assert tp["total_sent"] == 5.0 and tp["sent"][0]["name"] == "Someone"


def test_third_party_excludes_own_revolut_movements():
    txns = [
        _transfer("To Eduardo Eduardo", -3),
        _transfer("Revolut Bank UAB Sucursal em Portugal", -10),
        _transfer("Revolut Ltd", -41.2),
    ]
    tp = bd.third_party_breakdown(txns)
    names = {r["name"] for r in tp["sent"]}
    assert names == {"Eduardo Eduardo"}        # Revolut own-movements excluded
    assert tp["total_sent"] == 3.0


def test_own_movement_breakdown_collects_revolut_only():
    txns = [
        _transfer("To Eduardo Eduardo", -3),
        _transfer("Revolut Bank UAB Sucursal em Portugal", -10),
        _transfer("Revolut Ltd", -41.2),
        {"description": "Continente", "amount": -11.58, "raw": {"Type": "Card Payment"}},
    ]
    own = bd.own_movement_breakdown(txns)
    names = {r["name"] for r in own["sent"]}
    assert names == {"Revolut Bank UAB Sucursal em Portugal", "Revolut Ltd"}
    assert own["total_sent"] == 51.2
    # and the third-party view is disjoint — only the person
    tp = bd.third_party_breakdown(txns)
    assert {r["name"] for r in tp["sent"]} == {"Eduardo Eduardo"}


def test_third_party_empty_when_no_transfers():
    tp = bd.third_party_breakdown([{"description": "Bolt", "amount": -3.5, "raw": {"Type": "Card Payment"}}])
    assert tp["sent"] == [] and tp["received"] == []
    assert tp["total_sent"] == 0 and tp["total_received"] == 0
