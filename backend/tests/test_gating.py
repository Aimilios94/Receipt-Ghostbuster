"""The factored gate decision (services/gating.decide_gate) — the single source of
truth the /extract endpoint and the eval harness both use."""
from datetime import date
from types import SimpleNamespace

from app.models import ExtractionResult, LineItem, TaxLine
from app.services import gating

TODAY = date(2026, 10, 19)
SETTINGS = SimpleNamespace(confidence_threshold=0.8)


def _check(readable=True, auto_post=True, issues=None):
    return {"readable": readable, "auto_post": auto_post, "issues": list(issues or [])}


def _fields(use_printed=True, gross=10.0, vat_amount=1.0):
    return {"use_printed": use_printed, "breakdown": {"gross": gross}, "vat_amount": vat_amount}


def test_clean_confident_read_auto_posts():
    r = ExtractionResult(vendor="Pingo Doce", total=10.0, confidence=0.95)
    g = gating.decide_gate(r, _check(auto_post=True), _fields(), SETTINGS, TODAY)
    assert g["gated_to"] == "posted"
    assert g["guardrails_fired"] == []
    assert g["retake_suggested"] is False


def test_unreadable_is_rejected():
    r = ExtractionResult(vendor=None, total=None, confidence=0.9)
    g = gating.decide_gate(r, _check(readable=False, auto_post=False, issues=["No total amount could be read."]),
                           _fields(use_printed=False, gross=0), SETTINGS, TODAY)
    assert g["gated_to"] == "rejected"
    assert g["guardrails_fired"] == ["unreadable"]


def test_low_confidence_routes_to_review():
    r = ExtractionResult(vendor="X", total=10.0, confidence=0.6)
    g = gating.decide_gate(r, _check(auto_post=False, issues=["The model's confidence is low (60%)."]),
                           _fields(use_printed=False, gross=0), SETTINGS, TODAY)
    assert g["gated_to"] == "pending_review"
    assert "low_confidence" in g["guardrails_fired"]


def test_reconciling_read_suppresses_retake_despite_low_confidence():
    # A cent-perfect read at modest confidence must NOT nag a retake (D27 philosophy).
    r = ExtractionResult(vendor="X", total=10.0, confidence=0.72)
    g = gating.decide_gate(r, _check(auto_post=False, issues=[]), _fields(use_printed=True), SETTINGS, TODAY)
    assert g["read_reconciles"] is True
    assert g["retake_suggested"] is False
    assert g["gated_to"] == "pending_review"  # still reviewed, just not a retake nag


def test_estimated_vat_routes_to_review():
    r = ExtractionResult(vendor="Uber Eats", total=18.39, confidence=0.95, vat_estimated=True)
    g = gating.decide_gate(r, _check(auto_post=True), _fields(vat_amount=2.1), SETTINGS, TODAY)
    assert g["gated_to"] == "pending_review"
    assert "estimated_vat" in g["guardrails_fired"]


def test_self_consistency_mismatch_blocks_autopost():
    # Printed VAT table says 23% gross 10.00; item lines say 23% gross 2.00 -> inconsistent.
    r = ExtractionResult(
        vendor="Continente", total=10.0, confidence=0.95,
        tax_lines=[TaxLine(rate=23, net=8.13, vat=1.87, gross=10.0)],
        line_items=[LineItem(description="x", amount=2.0, vat_rate=23)],
    )
    g = gating.decide_gate(r, _check(auto_post=True), _fields(use_printed=False, gross=2.0), SETTINGS, TODAY)
    assert g["vat_inconsistent"] is True
    assert g["gated_to"] == "pending_review"
    assert "self_consistency" in g["guardrails_fired"]
    assert g["retake_suggested"] is True


def test_year_repair_forces_review_and_adds_issue():
    r = ExtractionResult(vendor="X", total=10.0, confidence=0.95, date=date(2026, 10, 14))
    g = gating.decide_gate(r, _check(auto_post=True), _fields(), SETTINGS, TODAY,
                           year_repair=(date(2021, 10, 14), date(2026, 10, 14)))
    assert g["gated_to"] == "pending_review"
    assert "year_repair" in g["guardrails_fired"]
    assert any("year looked misread" in i for i in g["issues"])
    assert g["retake_suggested"] is True


def test_duplicate_issue_forces_review():
    r = ExtractionResult(vendor="X", total=10.0, confidence=0.95)
    g = gating.decide_gate(r, _check(auto_post=True), _fields(), SETTINGS, TODAY,
                           duplicate_issue="Possible duplicate — X for €10.00 ...")
    assert g["gated_to"] == "pending_review"
    assert "duplicate" in g["guardrails_fired"]
    assert g["issues"][0].startswith("Possible duplicate")
