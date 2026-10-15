"""Receipt guardrails (T5+). Pure logic."""
from datetime import date

from app.models import ExtractionResult, LineItem
from app.services import validation as v

TODAY = date(2026, 10, 4)


def _res(**kw):
    base = dict(vendor="Lidl", date=date(2026, 10, 1), total=20.0, vat_rate=23, confidence=0.95)
    base.update(kw)
    return ExtractionResult(**base)


def test_clean_receipt_auto_posts():
    out = v.validate_receipt(_res(), today=TODAY)
    assert out["readable"] and out["auto_post"] and out["issues"] == []


def test_misread_old_year_is_flagged_not_posted():
    # The real bug: model read 2023 with high confidence.
    out = v.validate_receipt(_res(date=date(2023, 10, 26), confidence=0.9), today=TODAY)
    assert out["readable"] is True        # still usable
    assert out["auto_post"] is False      # but NOT auto-posted
    assert any("old" in i for i in out["issues"])


def test_future_date_flagged():
    out = v.validate_receipt(_res(date=date(2027, 1, 1)), today=TODAY)
    assert out["auto_post"] is False
    assert any("future" in i for i in out["issues"])


def test_no_total_is_unreadable():
    out = v.validate_receipt(_res(total=None), today=TODAY)
    assert out["readable"] is False
    assert out["auto_post"] is False


def test_low_confidence_goes_to_review():
    out = v.validate_receipt(_res(confidence=0.4), today=TODAY, confidence_threshold=0.8)
    assert out["auto_post"] is False
    assert any("confidence" in i.lower() for i in out["issues"])


def test_line_items_mismatch_flagged():
    items = [LineItem(description="a", amount=5.0), LineItem(description="b", amount=5.0)]
    out = v.validate_receipt(_res(total=20.0, line_items=items), today=TODAY)
    assert out["auto_post"] is False
    assert any("add up" in i for i in out["issues"])


def test_line_items_matching_total_is_clean():
    items = [LineItem(description="a", amount=12.0), LineItem(description="b", amount=8.0)]
    out = v.validate_receipt(_res(total=20.0, line_items=items), today=TODAY)
    assert out["auto_post"] is True


def test_repair_year_fixes_obvious_misread():
    # 2023-10-14 read on 2026-10-15: day/month fine, year wrong -> snap to 2026.
    assert v.repair_year(date(2023, 10, 14), date(2026, 10, 15)) == date(2026, 10, 14)


def test_repair_year_leaves_recent_dates_alone():
    assert v.repair_year(date(2026, 10, 14), date(2026, 10, 15)) is None


def test_repair_year_never_snaps_to_a_future_date():
    # Snapping 2023-10-14 to the current year would be 2026-10-14, which is after
    # today (2026-10-04) -> rejected; last year (2025) is too old -> None.
    assert v.repair_year(date(2023, 10, 14), date(2026, 10, 4)) is None


def test_repair_year_returns_none_when_no_recent_year_fits():
    # A genuinely old mid-January date: no current/last-year substitution lands in
    # the recent window, so we don't fabricate a correction.
    assert v.repair_year(date(2024, 1, 1), date(2026, 10, 15)) is None


def test_discount_receipt_does_not_flag_line_item_mismatch():
    # Uber Eats 1000017810: items 31.18, Special Offer -13.99, amount paid 18.39.
    # The item lines legitimately exceed the amount paid -> no mismatch flag.
    items = [LineItem(amount=27.98, vat_rate=23), LineItem(amount=1.20, vat_rate=23),
             LineItem(amount=2.00, vat_rate=23)]
    out = v.validate_receipt(
        _res(total=18.39, line_items=items, discount_total=13.99), today=TODAY
    )
    assert not any("add up to" in i for i in out["issues"])


def test_items_over_total_without_a_discount_still_flags():
    items = [LineItem(amount=27.98), LineItem(amount=2.00)]
    out = v.validate_receipt(_res(total=18.39, line_items=items), today=TODAY)
    assert any("add up to" in i for i in out["issues"])


def test_no_vat_signal_prompts_for_rate_and_category():
    # A VAT-exempt receipt (e.g. tobacco) or a misread: no rate, amount, table, or
    # per-line rate. Don't auto-post — ask the user to set 0% + a category in review.
    out = v.validate_receipt(
        _res(vat_rate=None, vat_amount=None), today=TODAY
    )
    assert out["auto_post"] is False
    assert any("No VAT found" in i for i in out["issues"])


def test_zero_rate_counts_as_a_vat_signal():
    # An explicit 0% reading is a real answer, not missing VAT -> no prompt.
    out = v.validate_receipt(_res(vat_rate=0, vat_amount=0), today=TODAY)
    assert not any("No VAT found" in i for i in out["issues"])


def test_estimated_per_line_rates_count_as_a_vat_signal():
    # Uber Eats: no printed VAT, but the model estimated per-line rates (13%/23%).
    # That is a VAT signal, so the "No VAT found" prompt must not fire.
    items = [LineItem(amount=16.50, vat_rate=13), LineItem(amount=1.18, vat_rate=23)]
    out = v.validate_receipt(
        _res(vat_rate=None, vat_amount=None, line_items=items, vat_estimated=True), today=TODAY
    )
    assert not any("No VAT found" in i for i in out["issues"])
