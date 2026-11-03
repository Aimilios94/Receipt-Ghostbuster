"""Schema coercion — the tolerant JSON parse (`_parse_json_payload`), the payload →
model coercion (`_to_result`), and the `ExtractionResult` validators. This is the
layer between a raw LLM response and the validated model the rest of the pipeline
trusts; it must survive fenced/garnished JSON, missing keys, and a confidence field
in whatever shape the model emits — without ever throwing away an otherwise-good read.
"""
from datetime import date

import pytest

from app.config import Settings
from app.models import ExtractionResult, LineItem, TaxLine, _to_number
from app.services import extraction
from app.services.extraction import _parse_json_payload, _to_result
from app.services.llm_trace import LlmCall


# --------------------------------------------------------------------------- #
# _parse_json_payload — tolerant extraction of a JSON object from model text
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"vendor": "Lidl", "total": 5.0}', {"vendor": "Lidl", "total": 5.0}),
        ('```json\n{"vendor": "Lidl", "total": 5.0}\n```', {"vendor": "Lidl", "total": 5.0}),
        ('```\n{"vendor": "Lidl"}\n```', {"vendor": "Lidl"}),
        ('Here is the receipt: {"vendor": "Lidl"} — hope it helps!', {"vendor": "Lidl"}),
        ('{"vendor": "Lidl", "meta": {"nested": 1}}', {"vendor": "Lidl", "meta": {"nested": 1}}),
        ("{}", {}),
        ('   {"a": 1}   ', {"a": 1}),
    ],
)
def test_parse_json_payload_tolerant(text, expected):
    assert _parse_json_payload(text) == expected


def test_parse_json_payload_raises_on_non_json():
    with pytest.raises(Exception):
        _parse_json_payload("sorry, I could not read the receipt")


# --------------------------------------------------------------------------- #
# _to_result — payload dict -> validated ExtractionResult, tolerating gaps
# --------------------------------------------------------------------------- #
def test_to_result_empty_payload_uses_safe_defaults():
    r = _to_result({})
    assert isinstance(r, ExtractionResult)
    assert r.vendor is None and r.total is None
    assert r.line_items == [] and r.tax_lines == []
    assert r.confidence == 0.0 and r.vat_estimated is False


def test_to_result_coerces_nested_lines():
    r = _to_result({
        "vendor": "Continente",
        "total": 12.30,
        "line_items": [{"description": "Bread", "amount": 2.12, "vat_rate": 6}],
        "tax_lines": [{"rate": 23, "net": 8.28, "vat": 1.90, "gross": 10.18}],
        "confidence": 0.9,
    })
    assert isinstance(r.line_items[0], LineItem) and r.line_items[0].vat_rate == 6
    assert isinstance(r.tax_lines[0], TaxLine) and r.tax_lines[0].gross == 10.18


def test_to_result_none_lists_become_empty():
    r = _to_result({"line_items": None, "tax_lines": None})
    assert r.line_items == [] and r.tax_lines == []


def test_to_result_blank_date_and_category_become_none():
    r = _to_result({"date": "", "category": ""})
    assert r.date is None and r.category is None


def test_to_result_parses_iso_date():
    r = _to_result({"date": "2026-10-05"})
    assert r.date == date(2026, 10, 5)


def test_to_result_confidence_as_percentage():
    # A model that returns 95 (percent) must land at 0.95, not be clamped to 1.0.
    assert _to_result({"confidence": 95}).confidence == pytest.approx(0.95)


def test_to_result_ignores_unknown_keys():
    r = _to_result({"vendor": "X", "total": 1.0, "some_future_field": "ignored"})
    assert r.vendor == "X" and r.total == 1.0


def test_to_result_vat_estimated_truthiness():
    assert _to_result({"vat_estimated": 1}).vat_estimated is True
    assert _to_result({"vat_estimated": 0}).vat_estimated is False


# --------------------------------------------------------------------------- #
# ExtractionResult._clamp_confidence — never reject a read over its confidence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        (0.85, 0.85),
        (95, 0.95),       # percentage
        (100, 1.0),       # percentage upper edge
        (150, 1.0),       # above 100 -> clamp, not /100
        (-5, 0.0),        # negative -> clamp
        ("0.7", 0.7),     # numeric string
        ("abc", 0.0),     # non-numeric -> 0, read kept
        (None, 0.0),      # missing -> 0, read kept
    ],
)
def test_confidence_clamp(raw, expected):
    assert ExtractionResult(confidence=raw).confidence == pytest.approx(expected)


def test_confidence_default_is_zero():
    assert ExtractionResult().confidence == 0.0


# --------------------------------------------------------------------------- #
# Locale-tolerant number coercion (_to_number) — a Portuguese receipt prints
# decimals with a comma ('32,95'); the vision model transcribes them verbatim.
# Regression: before this, such a payload raised a ValidationError in _to_result
# and the WHOLE receipt was dropped from the eval (n fell 26 -> 25) rather than
# scored. See eval/MODELS.md run 2026-11-03.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("32,95", 32.95),        # PT decimal comma
        ("1.234,56", 1234.56),   # dot thousands + comma decimal
        ("1 234,56", 1234.56),   # space thousands + comma decimal
        ("1,234.56", 1234.56),   # EN thousands + dot decimal
        ("€17,99", 17.99),       # currency symbol
        ("23%", 23.0),           # percent sign on a rate
        ("48.24", 48.24),        # already a dot-decimal string
        (48.24, 48.24),          # a real float passes straight through
        (6, 6.0),                # a real int passes straight through
        (None, None),            # missing stays missing
        ("", None),              # blank -> missing
        ("about twenty", "about twenty"),  # truly unparseable -> returned as-is
    ],
)
def test_to_number_coercion(raw, expected):
    assert _to_number(raw) == expected


def test_to_result_parses_comma_decimal_tax_lines():
    # The exact payload shape that crashed the 2026-11-03 local run: a VAT summary
    # table transcribed with comma decimals. It must now parse to real floats.
    r = _to_result({
        "vendor": "Pingo Doce",
        "total": "48,24",
        "tax_lines": [
            {"rate": 6, "net": "32,95", "vat": "1,98", "gross": "34,93"},
            {"rate": 23, "net": "10,82", "vat": "2,49", "gross": "13,31"},
        ],
        "confidence": 0.9,
    })
    assert r.total == pytest.approx(48.24)
    assert r.tax_lines[0].net == pytest.approx(32.95)
    assert r.tax_lines[0].vat == pytest.approx(1.98)
    assert r.tax_lines[1].gross == pytest.approx(13.31)


def test_to_result_coerces_comma_decimal_scalars():
    r = _to_result({"total": "12,30", "vat_amount": "1,98", "vat_rate": "23"})
    assert r.total == pytest.approx(12.30)
    assert r.vat_amount == pytest.approx(1.98)
    assert r.vat_rate == pytest.approx(23.0)


def test_extract_receipt_never_drops_receipt_on_unparseable_payload(monkeypatch):
    # Defense-in-depth: even a payload _to_number can't rescue must degrade to a
    # low-confidence read (which lands in review), never raise and drop the receipt.
    s = Settings(llm_provider="ollama")

    def bad_payload(image_bytes, media_type, settings, prompt, kind="receipt_extract"):
        return {"total": "about twenty euros"}, LlmCall(provider="ollama", model=settings.ollama_model)

    monkeypatch.setattr(extraction, "_extract_ollama", bad_payload)

    result, oriented, trace = extraction.extract_receipt(b"\xff\xd8\xff not-a-real-jpeg", "r.jpg", s)
    assert isinstance(result, ExtractionResult)
    assert result.confidence == 0.0  # degraded -> review, not auto-posted
