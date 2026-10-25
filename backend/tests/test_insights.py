"""Advice / insights rules (v0.4). Pure logic — no DB. Stdlib only."""
from datetime import date

from app.services import insights


# --- previous-month helper --------------------------------------------------
def test_prev_month_within_year():
    assert insights._prev_month("2026-09") == "2026-08"


def test_prev_month_crosses_year_boundary():
    assert insights._prev_month("2026-01") == "2025-12"


def _cat(name, budget=None):
    return {"id": name.lower(), "name": name, "budget_amount": budget}


def _exp(amount, category, d, *, status="posted", source="card"):
    return {
        "amount": amount, "category": category, "source": source,
        "expense_date": d, "status": status, "reconciled": True,
    }


# --- Rule 1: over budget ----------------------------------------------------
def test_over_budget_fires_when_spend_exceeds_budget():
    expenses = [_exp(120.0, "Groceries", "2026-09-04")]
    cats = [_cat("Groceries", 100.0)]
    out = insights.generate_insights(expenses, cats, [], "2026-09")
    rows = [r for r in out if r["kind"] == "over_budget"]
    assert len(rows) == 1
    r = rows[0]
    assert r["subject"] == "Groceries" and r["category"] == "Groceries"
    assert r["amount"] == 20.0
    assert r["metric"] == {"budget": 100.0, "actual": 120.0, "pct": 120}


def test_over_budget_silent_when_within_budget():
    expenses = [_exp(80.0, "Groceries", "2026-09-04")]
    cats = [_cat("Groceries", 100.0)]
    out = insights.generate_insights(expenses, cats, [], "2026-09")
    assert [r for r in out if r["kind"] == "over_budget"] == []


def test_over_budget_severity_escalates_past_alert_ratio():
    # 150 / 100 = 1.5x >= OVER_BUDGET_ALERT_RATIO (1.2) -> alert
    alert = insights.generate_insights(
        [_exp(150.0, "Groceries", "2026-09-04")], [_cat("Groceries", 100.0)], [], "2026-09"
    )[0]
    assert alert["severity"] == "alert"
    # 110 / 100 = 1.1x < 1.2 -> warning
    warn = insights.generate_insights(
        [_exp(110.0, "Groceries", "2026-09-04")], [_cat("Groceries", 100.0)], [], "2026-09"
    )[0]
    assert warn["severity"] == "warning"


def test_category_without_budget_never_nudges():
    expenses = [_exp(500.0, "Groceries", "2026-09-04")]
    out = insights.generate_insights(expenses, [_cat("Groceries", None)], [], "2026-09")
    assert [r for r in out if r["kind"] == "over_budget"] == []


# --- Rule 2: spend up vs last month -----------------------------------------
def test_spend_up_fires_on_large_increase():
    expenses = [
        _exp(60.0, "Dining & Cafes", "2026-08-10"),   # last month baseline
        _exp(120.0, "Dining & Cafes", "2026-09-10"),  # +100%, +60 EUR
    ]
    out = insights.generate_insights(expenses, [], [], "2026-09")
    rows = [r for r in out if r["kind"] == "spend_up"]
    assert len(rows) == 1
    assert rows[0]["metric"] == {"actual": 120.0, "prev": 60.0, "pct_change": 100}


def test_spend_up_muted_below_min_absolute_delta():
    # +100% but only +10 EUR (< SPEND_UP_MIN_DELTA 20) -> no nudge.
    expenses = [
        _exp(10.0, "Entertainment", "2026-08-10"),
        _exp(20.0, "Entertainment", "2026-09-10"),
    ]
    out = insights.generate_insights(expenses, [], [], "2026-09")
    assert [r for r in out if r["kind"] == "spend_up"] == []


def test_spend_up_muted_below_percent_threshold():
    # +30 EUR (>= min delta) but only +10% (< 25%) -> no nudge.
    expenses = [
        _exp(300.0, "Rent & Housing", "2026-08-01"),
        _exp(330.0, "Rent & Housing", "2026-09-01"),
    ]
    out = insights.generate_insights(expenses, [], [], "2026-09")
    assert [r for r in out if r["kind"] == "spend_up"] == []


def test_spend_up_needs_a_prior_month_baseline():
    # New category this month, nothing last month -> no comparison, no nudge.
    expenses = [_exp(200.0, "Travel", "2026-09-10")]
    out = insights.generate_insights(expenses, [], [], "2026-09")
    assert [r for r in out if r["kind"] == "spend_up"] == []


# --- Rule 3: unused subscription --------------------------------------------
def test_unused_subscription_from_flagged_status():
    subs = [{"vendor": "Gym Plus", "amount": 29.0, "annual_cost": 348.0,
             "cadence": "monthly", "status": "flagged", "last_seen": "2026-09-01"}]
    out = insights.generate_insights([], [], subs, "2026-09", today=date(2026, 9, 10))
    rows = [r for r in out if r["kind"] == "unused_subscription"]
    assert len(rows) == 1
    assert rows[0]["subject"] == "Gym Plus"
    assert rows[0]["amount"] == 348.0
    assert rows[0]["category"] is None


def test_unused_subscription_from_staleness():
    # last_seen ~4 months ago on a monthly cadence -> annotate marks it stale.
    subs = [{"vendor": "Old SaaS", "amount": 12.0, "annual_cost": 144.0,
             "cadence": "monthly", "status": "active", "last_seen": "2026-05-01"}]
    out = insights.generate_insights([], [], subs, "2026-09", today=date(2026, 9, 30))
    assert any(r["kind"] == "unused_subscription" for r in out)


def test_active_recent_subscription_does_not_nudge():
    subs = [{"vendor": "Netflix", "amount": 13.99, "annual_cost": 167.88,
             "cadence": "monthly", "status": "active", "last_seen": "2026-09-20"}]
    out = insights.generate_insights([], [], subs, "2026-09", today=date(2026, 9, 30))
    assert [r for r in out if r["kind"] == "unused_subscription"] == []


# --- ordering & ledger discipline -------------------------------------------
def test_sorted_by_severity_then_amount():
    expenses = [
        _exp(150.0, "Groceries", "2026-09-04"),   # over budget 100 -> alert (1.5x)
        _exp(110.0, "Transport & Fuel", "2026-09-04"),  # over budget 100 -> warning (1.1x)
    ]
    cats = [_cat("Groceries", 100.0), _cat("Transport & Fuel", 100.0)]
    out = insights.generate_insights(expenses, cats, [], "2026-09")
    assert [r["severity"] for r in out[:2]] == ["alert", "warning"]


def test_pending_review_spend_excluded_from_budget():
    # A pending_review receipt must not count toward budget (mirrors close.py).
    expenses = [_exp(500.0, "Groceries", "2026-09-04", status="pending_review")]
    out = insights.generate_insights(expenses, [_cat("Groceries", 100.0)], [], "2026-09")
    assert [r for r in out if r["kind"] == "over_budget"] == []
