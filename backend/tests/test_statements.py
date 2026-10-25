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


# --- idempotent re-upload: filter_new_transactions -------------------------

def _txn(date, amount, desc, balance=None):
    return {"txn_date": date, "amount": amount, "description": desc, "balance": balance}


def test_filter_exact_reupload_imports_nothing():
    rows = [
        _txn("2026-10-05", -11.58, "Continente", 74.27),
        _txn("2026-10-06", -4.14, "Continente", 68.89),
    ]
    to_insert, skipped = st.filter_new_transactions(rows, list(rows))
    assert to_insert == [] and skipped == 2


def test_filter_partial_overlap_imports_only_the_surplus():
    existing = [
        _txn("2026-10-05", -11.58, "Continente", 74.27),
        _txn("2026-10-06", -4.14, "Continente", 68.89),
    ]
    incoming = existing + [
        _txn("2026-10-20", -3.47, "Bolt", 103.79),
        _txn("2026-10-21", -11.11, "Anthropic", 82.83),
    ]
    to_insert, skipped = st.filter_new_transactions(incoming, existing)
    assert skipped == 2
    assert [r["description"] for r in to_insert] == ["Bolt", "Anthropic"]


def test_filter_preserves_same_day_repeats_by_balance():
    # Three identical €100 top-ups on one day — distinct running balances. All three
    # import on a first load, and all three are recognised as present on re-upload.
    topups = [
        _txn("2026-10-04", 100.0, "Google Pay top-up by *6517", 185.85),
        _txn("2026-10-04", 100.0, "Google Pay top-up by *6517", 285.85),
        _txn("2026-10-04", 100.0, "Google Pay top-up by *6517", 385.85),
    ]
    first, skipped_first = st.filter_new_transactions(topups, [])
    assert len(first) == 3 and skipped_first == 0
    again, skipped_again = st.filter_new_transactions(topups, topups)
    assert again == [] and skipped_again == 3


def test_filter_count_aware_without_balance():
    # No balance column: count reconciliation alone must neither collapse legit
    # repeats nor duplicate them. Two stored, three incoming -> one new.
    existing = [_txn("2026-10-04", 100.0, "Top up"), _txn("2026-10-04", 100.0, "Top up")]
    incoming = [
        _txn("2026-10-04", 100.0, "Top up"),
        _txn("2026-10-04", 100.0, "Top up"),
        _txn("2026-10-04", 100.0, "Top up"),
    ]
    to_insert, skipped = st.filter_new_transactions(incoming, existing)
    assert len(to_insert) == 1 and skipped == 2


def test_filter_description_whitespace_and_case_insensitive():
    existing = [_txn("2026-10-05", -11.58, "Continente", 74.27)]
    incoming = [_txn("2026-10-05", -11.58, "  continente ", 74.27)]
    to_insert, skipped = st.filter_new_transactions(incoming, existing)
    assert to_insert == [] and skipped == 1
