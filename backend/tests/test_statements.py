"""Bank-statement aggregation: period, in/out/net, and needs-receipt status."""
from app.services import statements as st


def _rows():
    return [
        {"txn_date": "2026-10-05", "amount": -11.58, "raw": {"Type": "Card Payment"}},
        {"txn_date": "2026-10-02", "amount": 100.0, "raw": {"Type": "Topup"}},
        {"txn_date": "2026-10-09", "amount": -4.48, "raw": {"Type": "Card Payment"},
         "matched_expense_id": "e1"},
        {"txn_date": "2026-10-08", "amount": -500.0, "raw": {"Type": "Transfer"}},
    ]


def test_statement_stats_period_and_totals():
    s = st.statement_stats(_rows())
    assert s["period_start"] == "2026-10-02"
    assert s["period_end"] == "2026-10-09"
    assert s["txn_count"] == 4
    assert s["total_in"] == 100.0
    assert s["total_out"] == 516.06      # 11.58 + 4.48 + 500.00
    assert s["net_amount"] == -416.06


def test_needs_receipt_only_unmatched_purchases():
    rows = _rows()
    flags = [st.needs_receipt(r) for r in rows]
    # Card payment unmatched -> True; top-up -> False; matched card -> False; transfer -> False
    assert flags == [True, False, False, False]


def test_no_receipt_leaves_the_cycle():
    purchase = {"amount": -11.58, "raw": {"Type": "Card Payment"}}
    assert st.needs_receipt(purchase) is True
    # Acknowledged as an online payment -> no longer needs a receipt.
    purchase["no_receipt"] = True
    assert st.needs_receipt(purchase) is False
    a = st.annotate_transaction(purchase)
    assert a["no_receipt"] is True and a["needs_receipt"] is False


def test_annotate_transaction_status():
    a = st.annotate_transaction({"amount": -11.58, "raw": {"Type": "Card Payment"}})
    assert a["reconcilable"] is True and a["needs_receipt"] is True and a["matched"] is False
    b = st.annotate_transaction({"amount": 100.0, "raw": {"Type": "Topup"}})
    assert b["reconcilable"] is False and b["needs_receipt"] is False
