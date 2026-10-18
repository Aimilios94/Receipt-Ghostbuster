"""Categorization: rules first, LLM suggestion as fallback. Pure logic."""
from app.services.categorization import categorize

VALID = {
    "Groceries",
    "Dining & Cafes",
    "Transport & Fuel",
    "Software & Subscriptions",
    "Uncategorized",
}


def test_rules_match_known_vendor():
    assert categorize("Lidl Athens") == "Groceries"
    assert categorize("Starbucks Syntagma") == "Dining & Cafes"


def test_uber_eats_is_dining_not_transport():
    # "Uber Eats" (food delivery) must beat the generic "uber" ride rule, while a
    # plain Uber ride still maps to Transport. Order-sensitive first-match behaviour.
    assert categorize("Uber Eats") == "Dining & Cafes"
    assert categorize("UberEats") == "Dining & Cafes"
    assert categorize("Glovo") == "Dining & Cafes"
    assert categorize("Uber *trip helsinki") == "Transport & Fuel"


def test_rules_win_over_llm_suggestion():
    # A rule hit is deterministic and must not be overridden by the LLM.
    called = []

    def llm(_):
        called.append(True)
        return "Entertainment"

    assert categorize("Lidl", llm_fallback=llm) == "Groceries"
    assert called == []  # fallback never invoked when a rule matches


def test_llm_fallback_fills_unknown_vendor():
    # Continente is a real gap: not in the keyword rules. The LLM, which already
    # read the receipt, suggests "Groceries" and it is accepted.
    result = categorize(
        "Continente",
        llm_fallback=lambda _: "Groceries",
        valid_categories=VALID,
    )
    assert result == "Groceries"


def test_llm_suggestion_rejected_when_not_a_valid_category():
    result = categorize(
        "PD OLAIAS",
        llm_fallback=lambda _: "Snacks",  # not a real category
        valid_categories=VALID,
    )
    assert result == "Uncategorized"


def test_no_fallback_returns_uncategorized():
    assert categorize("Some Unknown Shop") == "Uncategorized"


def test_null_llm_suggestion_returns_uncategorized():
    result = categorize(
        "Pingo Doce",
        llm_fallback=lambda _: None,  # LLM was unsure
        valid_categories=VALID,
    )
    assert result == "Uncategorized"
