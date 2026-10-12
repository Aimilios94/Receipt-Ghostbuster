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
  "line_items": [ { "description": string, "quantity": number|null, "unit_price": number|null, "amount": number|null } ],
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

DATE RULES (important — these receipts are European, from Portugal):
- Printed dates are DAY-first, never US month-first. Read "DD/MM/YYYY" or "DD-MM-YYYY".
  Example: "03/10/2026" means 3 October 2026 -> output "2026-10-03" (NOT 10 March).
- A two-digit year like "26-10-09" is YY-MM-DD -> "2026-10-09". If a full four-digit
  date also appears on the receipt, prefer that one.
- Prefer the transaction/terminal date near the total or payment line over any other
  printed date. Always output the date in ISO "YYYY-MM-DD".

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
        "total": round(len(image_bytes) % 5000 / 100 + 1.0, 2),
        "vat_amount": None,
        "vat_rate": 24,
        "currency": "EUR",
        "line_items": [],
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
