"""Refund/cancel email drafting (Phase 2, T14). Template path — no LLM."""
from types import SimpleNamespace

from app.services import refund_email


# A settings stub that forces the deterministic template path.
MOCK = SimpleNamespace(llm_provider="mock", anthropic_api_key="", anthropic_model="x")

SUB = {"vendor": "Gym Plus", "amount": 29.0, "cadence": "monthly", "annual_cost": 348.0}


def test_cancel_draft_mentions_vendor_and_amount():
    d = refund_email.draft_email(SUB, "cancel", MOCK)
    assert "Gym Plus" in d["subject"]
    assert "cancel" in d["body"].lower()
    assert "29" in d["body"]
    assert "[Your name]" in d["body"]        # signed off with a placeholder, not invented


def test_refund_draft_is_distinct():
    d = refund_email.draft_email(SUB, "refund", MOCK)
    assert "refund" in d["subject"].lower()
    assert "refund" in d["body"].lower()


def test_never_raises_without_llm():
    # No key + anthropic provider should still return a template, not crash.
    settings = SimpleNamespace(llm_provider="anthropic", anthropic_api_key="", anthropic_model="x")
    d = refund_email.draft_email(SUB, "cancel", settings)
    assert d["subject"] and d["body"]
