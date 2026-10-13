"""Receipt extraction via a vision LLM.

Provider-agnostic. The LLM returns ONLY what it read plus a self-reported
confidence — it does not decide posting status and does not do reconciliation or
VAT math (that is all done in code downstream). Supported providers: anthropic,
openai, mock. 'mock' lets the whole pipeline run before an API key is supplied.
"""
from __future__ import annotations

import base64
import json
from typing import Any

from ..config import Settings
from ..models import ExtractionResult

EXTRACTION_PROMPT = """You are a receipt-reading assistant. Read the receipt image and \
return ONLY a JSON object (no prose, no markdown fences) with exactly these keys:
{
  "vendor": string|null,
  "date": "YYYY-MM-DD"|null,
  "total": number|null,          // gross total paid, VAT-inclusive
  "vat_amount": number|null,     // VAT shown on the receipt, if any
  "vat_rate": number|null,       // VAT percentage, e.g. 24
  "currency": string|null,       // ISO code if visible, else null
  "line_items": [ { "description": string, "quantity": number|null, "unit_price": number|null, "amount": number|null, "vat_rate": number|null } ],
  "confidence": number           // 0.0-1.0, YOUR confidence the fields are correct
}

ORIENTATION:
- The photo may be rotated or sideways. Mentally rotate it so the text is upright
  and readable before extracting anything.

LINE ITEMS:
- Extract EVERY item row in the itemized section — one object per product line,
  including short receipts with only 2-3 items. Do NOT stop after the first item.
- The line items should add up to (or close to) the printed total; if your items
  fall far short of the total, you have likely missed some — look again.
- `amount` is the GROSS (VAT-inclusive) price for that line.

PER-LINE VAT (important — these receipts can mix VAT rates on one ticket):
- Portuguese receipts tag each line with a VAT CODE (a letter like A/B/C or a number)
  and print a VAT SUMMARY table near the total mapping each code to a rate and base,
  e.g. "A 23%", "B 13%", "C 6%". Portuguese rates are 23, 13 and 6 (Madeira/Azores
  differ). Use that table to set each line's `vat_rate` to the correct percentage.
- If a line shows no code and no rate can be inferred, set its `vat_rate` to null.
- Put the per-line percentage (e.g. 23), NOT the VAT amount, in `vat_rate`. Keep the
  top-level `vat_rate`/`vat_amount` as the receipt's overall/summary figures.

DATE RULES (important — these receipts are European, from Portugal):
- The DOCUMENT date is printed near the TOP, by the invoice number (e.g.
  "Nro:FS BEB002/322839 05/10/2026 12:34" or next to "Fatura"/"Fatura Simplificada").
  Use THIS as the date. It is DAY-first "DD/MM/YYYY": "05/10/2026" -> "2026-10-05"
  (5 October, NOT 10 May, NOT the 26th).
- Printed dates are DAY-first, never US month-first. "03/10/2026" -> "2026-10-03".
- Near the BOTTOM, the card-terminal block often prints a SHORT date like "26-10-05"
  (this is YY-MM-DD = 2026-10-05, the SAME day). Do NOT read its last field ("05") as
  the month or the first field ("26") as the day. When a full four-digit-year date
  exists near the top, ALWAYS prefer that one and ignore the short terminal date.
- Always output the date in ISO "YYYY-MM-DD". If two readings disagree, prefer the
  top four-digit document date.

Be conservative with confidence: if the image is blurry, cut off, rotated, or ambiguous, \
report a low value. Do not invent values you cannot read."""


def _guess_media_type(filename: str | None, content: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".png") or content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if name.endswith((".webp",)):
        return "image/webp"
    return "image/jpeg"


def _parse_json_payload(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def _extract_anthropic(image_bytes: bytes, media_type: str, settings: Settings) -> dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
    return _parse_json_payload(text)


def _extract_openai(image_bytes: bytes, media_type: str, settings: Settings) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    resp = client.chat.completions.create(
        model=settings.openai_model,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {
                        "type": "image_url",
                        # "high" detail = full-resolution tiling. Much better OCR on
                        # dense, crumpled, or rotated receipts (worth the extra tokens).
                        "image_url": {"url": f"data:{media_type};base64,{b64}", "detail": "high"},
                    },
                ],
            }
        ],
    )
    return _parse_json_payload(resp.choices[0].message.content or "{}")


def _extract_mock(image_bytes: bytes, filename: str | None) -> dict[str, Any]:
    """Deterministic stand-in so the pipeline works without an API key.
    Confidence is intentionally mid so it lands in the review queue by default."""
    return {
        "vendor": "MOCK VENDOR (set LLM_PROVIDER=anthropic + key for real extraction)",
        "date": None,
        "total": 12.30,
        "vat_amount": None,
        "vat_rate": 23,
        "currency": "EUR",
        # Two rates on one ticket so the per-line VAT path is exercised in mock mode.
        "line_items": [
            {"description": "Bread (6%)", "quantity": 1, "unit_price": 2.12, "amount": 2.12, "vat_rate": 6},
            {"description": "Cleaning spray (23%)", "quantity": 1, "unit_price": 10.18, "amount": 10.18, "vat_rate": 23},
        ],
        "confidence": 0.5,
    }


def extract_receipt(
    image_bytes: bytes,
    filename: str | None,
    settings: Settings,
) -> ExtractionResult:
    media_type = _guess_media_type(filename, image_bytes)
    provider = settings.llm_provider.lower()

    if provider == "mock":
        payload = _extract_mock(image_bytes, filename)
    elif provider == "anthropic":
        payload = _extract_anthropic(image_bytes, media_type, settings)
    elif provider == "openai":
        payload = _extract_openai(image_bytes, media_type, settings)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")

    # Coerce into the validated model; tolerate missing keys.
    return ExtractionResult(
        vendor=payload.get("vendor"),
        date=payload.get("date") or None,
        total=payload.get("total"),
        vat_amount=payload.get("vat_amount"),
        vat_rate=payload.get("vat_rate"),
        currency=payload.get("currency"),
        line_items=payload.get("line_items") or [],
        confidence=float(payload.get("confidence") or 0.0),
    )
