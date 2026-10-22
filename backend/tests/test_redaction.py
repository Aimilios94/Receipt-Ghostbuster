"""Redaction of IBANs / card numbers before text is sent to a cloud LLM or stored.

Over-redaction is the safe direction; the must-nots are (a) leaking an account
identifier and (b) corrupting a real amount/date the structuring needs.
"""
from app.services.redaction import redact_sensitive


def test_masks_portuguese_iban_compact_and_spaced():
    assert "PT50" not in redact_sensitive("Conta: PT50000201231234567890154")
    assert "IBAN REDACTED" in redact_sensitive("IBAN PT50 0002 0123 1234 5678 9015 4")


def test_masks_card_pan_grouped_and_plain():
    assert "4111" not in redact_sensitive("Cartao 4111 1111 1111 1111")
    assert "CARD REDACTED" in redact_sensitive("PAN: 4111111111111111")


def test_leaves_amounts_dates_and_short_numbers_untouched():
    line = "05/10/2026  COMPRA CONTINENTE LISBOA  -11,58  1.234,56"
    out = redact_sensitive(line)
    assert out == line  # no 13-19 digit run, no IBAN -> unchanged
    # A terminal/ref of a few digits must survive (it's not a PAN).
    assert redact_sensitive("Terminal 01448684 Tr059") == "Terminal 01448684 Tr059"


def test_empty_and_clean_text():
    assert redact_sensitive("") == ""
    assert redact_sensitive("just some words 23%") == "just some words 23%"
