"""Receipt guardrails (T5+). Pure logic."""
from datetime import date

from app.models import ExtractionResult, LineItem
from app.services import validation as v

TODAY = date(2026, 10, 4)


def _res(**kw):
    base = dict(vendor="Lidl", date=date(2026, 10, 1), total=20.0, confidence=0.95)
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
