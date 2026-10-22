"""Redact sensitive identifiers from text before it leaves the machine.

Bank-statement PDFs can carry an IBAN and card numbers that the extractor does
NOT need — it only wants {date, description, amount}. Masking them before the
text is sent to a cloud LLM (and before it is stored) is data minimisation: the
provider never sees an account number it has no reason to hold. This is a pure,
unit-tested helper so the masking is auditable.

Scope + honesty: this redacts the TEXT path (the bank-PDF structuring call). It
does NOT touch receipt *images* — an image can't be text-redacted, so the honest
mitigation there is the local Ollama model (data never leaves the machine) and
the retention policy, both documented in docs/PRIVACY.md. Over-redaction is the
safe direction: a masked reference number costs nothing (the structuring only
needs date/description/amount); a leaked IBAN would be a real disclosure.
"""
from __future__ import annotations

import re

# IBAN: 2-letter country + 2 check digits + 11-30 alphanumeric (PT50 + 21 digits = 25).
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,8}[ ]?[A-Z0-9]{0,4}\b")

# Card PAN: 13-19 digits, optionally grouped by spaces/dashes (e.g. "4111 1111 1111 1111").
# Amounts (e.g. "1.234,56", "-11,58") never reach 13 consecutive digits, so they're safe.
_PAN_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def redact_sensitive(text: str) -> str:
    """Return `text` with IBANs and card numbers masked. Idempotent and safe on
    text that contains neither (returns it unchanged)."""
    if not text:
        return text
    text = _IBAN_RE.sub("[IBAN REDACTED]", text)

    def _mask_pan(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) < 13:  # separators inflated a shorter run; leave it alone
            return m.group(0)
        return "[CARD REDACTED]"

    return _PAN_RE.sub(_mask_pan, text)
