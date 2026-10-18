"""Categorization: rules first, LLM fallback for unknowns.

A keyword->category rules map handles the common vendors deterministically (fast,
free, auditable). Anything unmatched can fall back to the LLM (optional callable),
and if that is unavailable we return 'Uncategorized' so nothing is silently wrong.
"""
from __future__ import annotations

from typing import Callable

# vendor/description keyword -> category. Lowercase substring match.
DEFAULT_RULES: dict[str, str] = {
    "lidl": "Groceries",
    "aldi": "Groceries",
    "sklavenitis": "Groceries",
    "ab vasilopoulos": "Groceries",
    "carrefour": "Groceries",
    "starbucks": "Dining & Cafes",
    "mcdonald": "Dining & Cafes",
    "coffee": "Dining & Cafes",
    "cafe": "Dining & Cafes",
    "restaurant": "Dining & Cafes",
    "taverna": "Dining & Cafes",
    "shell": "Transport & Fuel",
    "bp ": "Transport & Fuel",
    "eko": "Transport & Fuel",
    # Food delivery — must come BEFORE "uber" so "Uber Eats" isn't caught by the
    # ride rule (first substring match wins). Plain "Uber" (rides) still -> Transport.
    "uber eats": "Dining & Cafes",
    "ubereats": "Dining & Cafes",
    "glovo": "Dining & Cafes",
    "bolt food": "Dining & Cafes",
    "uber": "Transport & Fuel",
    "taxi": "Transport & Fuel",
    "dei": "Utilities",
    "deh": "Utilities",
    "cosmote": "Utilities",
    "vodafone": "Utilities",
    "nova": "Utilities",
    "netflix": "Software & Subscriptions",
    "spotify": "Software & Subscriptions",
    "openai": "Software & Subscriptions",
    "anthropic": "Software & Subscriptions",
    "github": "Software & Subscriptions",
    "google": "Software & Subscriptions",
    "adobe": "Software & Subscriptions",
    "aws": "Software & Subscriptions",
    "pharmacy": "Health & Pharmacy",
    "farmakeio": "Health & Pharmacy",
    "public": "Office & Supplies",
    "plaisio": "Office & Supplies",
    "ikea": "Office & Supplies",
    "aegean": "Travel",
    "ryanair": "Travel",
    "booking.com": "Travel",
    "airbnb": "Travel",
    "cinema": "Entertainment",
}


def categorize(
    vendor: str | None,
    note: str | None = None,
    *,
    llm_fallback: Callable[[str], str | None] | None = None,
    valid_categories: set[str] | None = None,
) -> str:
    haystack = " ".join(filter(None, [vendor, note])).lower()
    for keyword, category in DEFAULT_RULES.items():
        if keyword in haystack:
            return category

    if llm_fallback and haystack.strip():
        guess = llm_fallback(haystack)
        if guess and (valid_categories is None or guess in valid_categories):
            return guess

    return "Uncategorized"
