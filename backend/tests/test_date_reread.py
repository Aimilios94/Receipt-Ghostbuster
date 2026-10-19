"""Focused date re-read pass (the 'think twice about the date' fix).

Regression for the Continente 1000017808 receipt: the model kept reading the year
as 2023/2014 on a crumpled top line. When a date looks wrong we re-read ONLY the
date and accept the second reading only if it is plausible.
"""
from datetime import date

from app.config import Settings
from app.services import extraction

TODAY = date(2026, 10, 15)


def _settings():
    return Settings(llm_provider="openai", openai_api_key="test-key")


def test_parse_iso_date_tolerant():
    assert extraction._parse_iso_date("2026-10-14") == date(2026, 10, 14)
    assert extraction._parse_iso_date("2026-10-14T13:33") == date(2026, 10, 14)
    assert extraction._parse_iso_date(None) is None
    assert extraction._parse_iso_date("not a date") is None


def test_reread_accepts_plausible_recent_date(monkeypatch):
    # _extract_openai now returns (payload, LlmCall); reread_date unpacks the tuple.
    monkeypatch.setattr(extraction, "_extract_openai", lambda *a, **k: ({"date": "2026-10-14"}, None))
    out = extraction.reread_date(b"img", "r.jpg", _settings(), TODAY)
    assert out == date(2026, 10, 14)


def test_reread_rejects_future_date(monkeypatch):
    monkeypatch.setattr(extraction, "_extract_openai", lambda *a, **k: ({"date": "2027-01-01"}, None))
    assert extraction.reread_date(b"img", "r.jpg", _settings(), TODAY) is None


def test_reread_rejects_absurdly_old_date(monkeypatch):
    # A second reading that is STILL years old is not trusted — keep the original.
    monkeypatch.setattr(extraction, "_extract_openai", lambda *a, **k: ({"date": "2023-10-14"}, None))
    assert extraction.reread_date(b"img", "r.jpg", _settings(), TODAY) is None


def test_reread_swallows_provider_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(extraction, "_extract_openai", boom)
    assert extraction.reread_date(b"img", "r.jpg", _settings(), TODAY) is None


def test_reread_is_noop_for_mock_provider():
    assert extraction.reread_date(b"img", "r.jpg", Settings(llm_provider="mock"), TODAY) is None
