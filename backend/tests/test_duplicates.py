"""Duplicate detection at upload: match on vendor + exact total within a date
window, because the date is the most-misread field (DECISIONS D16). Pure logic
via match_duplicate_rows — no DB."""
from app.repository import match_duplicate_rows


def _row(vendor, amount, expense_date, id="x"):
    return {"id": id, "vendor": vendor, "amount": amount, "expense_date": expense_date}


LEDGER = [
    _row("Pingo Doce", 48.24, "2026-10-03", id="keep"),
    _row("Continente", 11.58, "2026-10-05", id="other"),
]


def test_same_vendor_amount_different_date_within_window_is_duplicate():
    # The real Pingo Doce case: same vendor + €48.24, dates 9 days apart (03 vs 08).
    hits = match_duplicate_rows(LEDGER, "Pingo Doce", 48.24, "2026-10-08")
    assert [h["id"] for h in hits] == ["keep"]


def test_same_vendor_amount_date_outside_window_is_not_duplicate():
    # Same amount months later = a genuine repeat purchase, not a duplicate upload.
    hits = match_duplicate_rows(LEDGER, "Pingo Doce", 48.24, "2027-02-01")
    assert hits == []


def test_different_amount_is_not_duplicate():
    hits = match_duplicate_rows(LEDGER, "Pingo Doce", 40.00, "2026-10-03")
    assert hits == []


def test_different_vendor_is_not_duplicate():
    hits = match_duplicate_rows(LEDGER, "Lidl", 48.24, "2026-10-03")
    assert hits == []


def test_vendor_match_is_case_and_space_insensitive():
    hits = match_duplicate_rows(LEDGER, "  pingo doce ", 48.24, "2026-10-03")
    assert [h["id"] for h in hits] == ["keep"]


def test_amount_within_half_cent_matches():
    hits = match_duplicate_rows(LEDGER, "Pingo Doce", 48.243, "2026-10-03")
    assert [h["id"] for h in hits] == ["keep"]


def test_missing_date_falls_back_to_vendor_plus_amount():
    # If either date is missing/unparseable, the strong fingerprint still flags it.
    hits = match_duplicate_rows(LEDGER, "Pingo Doce", 48.24, None)
    assert [h["id"] for h in hits] == ["keep"]
    ledger_no_date = [_row("Pingo Doce", 48.24, None, id="nd")]
    assert [h["id"] for h in match_duplicate_rows(ledger_no_date, "Pingo Doce", 48.24, "2026-10-03")] == ["nd"]


def test_no_vendor_or_amount_returns_empty():
    assert match_duplicate_rows(LEDGER, None, 48.24, "2026-10-03") == []
    assert match_duplicate_rows(LEDGER, "Pingo Doce", None, "2026-10-03") == []


def test_vendor_branch_suffix_matches_brand_prefix():
    # The real re-upload case: the model read the branch the second time.
    # 'Pingo Doce' (stored) vs 'Pingo Doce - PD Olaias' (new) — same store.
    hits = match_duplicate_rows(LEDGER, "Pingo Doce - PD Olaias", 48.24, "2026-10-03")
    assert [h["id"] for h in hits] == ["keep"]
    # ...and the reverse direction (stored has the branch, new is just the brand).
    ledger_branch = [_row("Pingo Doce - PD Olaias", 48.24, "2026-10-03", id="b")]
    assert [h["id"] for h in match_duplicate_rows(ledger_branch, "Pingo Doce", 48.24, "2026-10-03")] == ["b"]


def test_different_brand_does_not_prefix_match():
    # Not a prefix either way → different store, not a duplicate.
    assert match_duplicate_rows(LEDGER, "Continente Bom Dia", 48.24, "2026-10-03") == []
    # Same tokens in a different order is not a brand-prefix match.
    reordered = [_row("Doce Pingo", 48.24, "2026-10-03", id="r")]
    assert match_duplicate_rows(reordered, "Pingo Doce", 48.24, "2026-10-03") == []
