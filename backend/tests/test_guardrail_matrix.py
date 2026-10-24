"""Guardrail matrix — the REAL validate_receipt feeding the REAL decide_gate, across
a grid of receipt shapes, plus guardrail precedence / stacking and the retake truth
table. The unit behaviours live in test_validation.py and test_gating.py; this file
guards the *integration* between them and the combinations, so a change that makes the
two drift apart (or mis-orders the guardrails) fails here.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.models import ExtractionResult, LineItem, TaxLine
from app.services import gating, validation

TODAY = date(2026, 10, 19)


def _gate(result, *, fields=None, year_repair=None, duplicate_issue=None, threshold=0.8):
    """Run the shipped pipeline: deterministic validate_receipt -> decide_gate."""
    check = validation.validate_receipt(result, today=TODAY, confidence_threshold=threshold)
    f = fields if fields is not None else {"use_printed": False, "breakdown": {}, "vat_amount": result.vat_amount}
    settings = SimpleNamespace(confidence_threshold=threshold)
    return gating.decide_gate(result, check, f, settings, TODAY,
                              year_repair=year_repair, duplicate_issue=duplicate_issue)


def _clean(**kw):
    base = dict(vendor="Pingo Doce", date=date(2026, 10, 15), total=20.0, vat_rate=23, confidence=0.95)
    base.update(kw)
    return ExtractionResult(**base)


# --------------------------------------------------------------------------- #
# End-to-end routing grid (real validate_receipt -> real decide_gate)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name, result, fields, expect_gate, expect_fired_subset",
    [
        ("clean_confident", _clean(), {"use_printed": True, "breakdown": {"gross": 20.0}, "vat_amount": 3.0},
         "posted", set()),
        ("no_total_unreadable", _clean(total=None, vendor=None), None, "rejected", {"unreadable"}),
        ("low_confidence", _clean(confidence=0.5), None, "pending_review", {"low_confidence"}),
        ("future_date", _clean(date=date(2027, 1, 1)), None, "pending_review", set()),
        ("old_date", _clean(date=date(2026, 1, 1)), None, "pending_review", set()),
        ("missing_vendor", _clean(vendor=None), None, "pending_review", set()),
        ("no_vat_signal", _clean(vat_rate=None, vat_amount=None), None, "pending_review", set()),
        ("estimated_vat", _clean(vat_estimated=True),
         {"use_printed": False, "breakdown": {}, "vat_amount": 2.1}, "pending_review", {"estimated_vat"}),
    ],
)
def test_routing_grid(name, result, fields, expect_gate, expect_fired_subset):
    g = _gate(result, fields=fields)
    assert g["gated_to"] == expect_gate, name
    assert expect_fired_subset.issubset(set(g["guardrails_fired"])), name


# --------------------------------------------------------------------------- #
# Precedence: an unreadable read short-circuits EVERY other guardrail
# --------------------------------------------------------------------------- #
def test_unreadable_short_circuits_all_other_guardrails():
    # No total (unreadable) AND it would otherwise trip estimated_vat + duplicate +
    # year_repair. decide_gate must return early with only the unreadable tag.
    r = _clean(total=None, vendor=None, vat_estimated=True)
    g = _gate(r, fields={"use_printed": False, "breakdown": {}, "vat_amount": 2.0},
              year_repair=(date(2021, 1, 1), date(2026, 1, 1)),
              duplicate_issue="Possible duplicate …")
    assert g["gated_to"] == "rejected"
    assert g["guardrails_fired"] == ["unreadable"]
    assert "year_repair" not in g["guardrails_fired"]
    assert "duplicate" not in g["guardrails_fired"]


# --------------------------------------------------------------------------- #
# Stacking: several independent guardrails fire together on one readable read
# --------------------------------------------------------------------------- #
def test_guardrails_stack_on_one_read():
    r = _clean(confidence=0.5, vat_estimated=True)
    g = _gate(r, fields={"use_printed": False, "breakdown": {}, "vat_amount": 2.0},
              year_repair=(date(2026, 1, 1), date(2026, 10, 1)),
              duplicate_issue="Possible duplicate — Pingo Doce for €20.00 …")
    fired = set(g["guardrails_fired"])
    assert {"year_repair", "duplicate", "estimated_vat", "low_confidence"}.issubset(fired)
    assert g["gated_to"] == "pending_review"
    # The caller's messages land first, in order.
    assert g["issues"][0].startswith("Possible duplicate") or "year looked misread" in g["issues"][0]


def test_self_consistency_and_estimated_vat_both_fire():
    r = ExtractionResult(
        vendor="Continente", total=10.0, confidence=0.95, vat_estimated=True,
        tax_lines=[TaxLine(rate=23, net=8.13, vat=1.87, gross=10.0)],
        line_items=[LineItem(description="x", amount=2.0, vat_rate=23)],
    )
    g = _gate(r, fields={"use_printed": False, "breakdown": {"gross": 2.0}, "vat_amount": 1.5})
    fired = set(g["guardrails_fired"])
    assert {"estimated_vat", "self_consistency"}.issubset(fired)
    assert g["gated_to"] == "pending_review"


# --------------------------------------------------------------------------- #
# retake_suggested truth table
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name, result, fields, year_repair, expect_retake",
    [
        # Reconciling read at low confidence -> review, but NO retake nag.
        ("reconciles_low_conf", _clean(confidence=0.6),
         {"use_printed": True, "breakdown": {"gross": 20.0}, "vat_amount": 3.0}, None, False),
        # Low confidence AND does not reconcile -> retake.
        ("low_conf_no_reconcile", _clean(confidence=0.6),
         {"use_printed": False, "breakdown": {}, "vat_amount": None}, None, True),
        # Suspect date -> retake even at high confidence.
        ("future_date", _clean(date=date(2027, 1, 1)),
         {"use_printed": True, "breakdown": {"gross": 20.0}, "vat_amount": 3.0}, None, True),
        # Year repaired -> retake.
        ("year_repair", _clean(),
         {"use_printed": True, "breakdown": {"gross": 20.0}, "vat_amount": 3.0},
         (date(2021, 10, 15), date(2026, 10, 15)), True),
        # Clean, reconciling, confident -> no retake.
        ("clean", _clean(),
         {"use_printed": True, "breakdown": {"gross": 20.0}, "vat_amount": 3.0}, None, False),
    ],
)
def test_retake_truth_table(name, result, fields, year_repair, expect_retake):
    g = _gate(result, fields=fields, year_repair=year_repair)
    assert g["retake_suggested"] is expect_retake, name


# --------------------------------------------------------------------------- #
# Self-consistency tolerance boundary (the 10%-of-total divergence threshold)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("line_gross, inconsistent", [(9.3, False), (8.0, True)])
def test_self_consistency_tolerance_boundary(line_gross, inconsistent):
    # Printed table says 23% gross 10.00; tolerance = max(1.0, 0.10*total)=1.0.
    # A line gross of 9.3 diverges 0.7 (<=1.0 -> consistent); 8.0 diverges 2.0 (-> inconsistent).
    r = ExtractionResult(
        vendor="X", total=10.0, confidence=0.95,
        tax_lines=[TaxLine(rate=23, net=8.13, vat=1.87, gross=10.0)],
        line_items=[LineItem(description="x", amount=line_gross, vat_rate=23)],
    )
    g = _gate(r, fields={"use_printed": False, "breakdown": {"gross": line_gross}, "vat_amount": 1.5})
    assert g["vat_inconsistent"] is inconsistent
    assert ("self_consistency" in g["guardrails_fired"]) is inconsistent
