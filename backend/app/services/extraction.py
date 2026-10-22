"""Receipt extraction via a vision LLM.

Provider-agnostic. The LLM returns ONLY what it read plus a self-reported
confidence — it does not decide posting status and does not do reconciliation or
VAT math (that is all done in code downstream). Supported providers: anthropic,
openai, mock. 'mock' lets the whole pipeline run before an API key is supplied.
"""
from __future__ import annotations

import base64
import datetime
import io
import json
import time
from typing import Any

from ..config import Settings
from ..models import ExtractionResult
from .llm_trace import (
    LlmCall,
    aggregate,
    wrap_anthropic_if_enabled,
    wrap_openai_if_enabled,
)

try:  # Pillow is optional — without it we just skip server-side rotation.
    from PIL import Image, ImageOps

    _PIL_OK = True
except Exception:  # noqa: BLE001
    _PIL_OK = False

EXTRACTION_PROMPT = """You are a receipt-reading assistant. STEP 0: first check the image
orientation and mentally rotate it upright (see ORIENTATION below) — the store name must be
at the TOP with lines reading left-to-right BEFORE you read anything. Then
return ONLY a JSON object (no prose, no markdown fences) with exactly these keys:
{
  "vendor": string|null,
  "date": "YYYY-MM-DD"|null,
  "total": number|null,          // gross total paid, VAT-inclusive
  "vat_amount": number|null,     // VAT shown on the receipt, if any
  "vat_rate": number|null,       // VAT percentage, e.g. 24
  "currency": string|null,       // ISO code if visible, else null
  "line_items": [ { "description": string, "quantity": number|null, "unit_price": number|null, "amount": number|null, "vat_rate": number|null } ],
  "tax_lines": [ { "rate": number, "net": number|null, "vat": number|null, "gross": number|null } ],
  "discount_total": number|null, // total discount applied, as a POSITIVE number, else null
  "vat_estimated": boolean,      // true if you ESTIMATED the per-line vat_rate (see below)
  "category": string|null,       // best-fit category from the list below, or null
  "confidence": number           // 0.0-1.0, YOUR confidence the fields are correct
}

READ, NEVER GUESS (critical):
- Transcribe only the numbers that are actually PRINTED on the receipt. Do NOT invent,
  adjust, or back-calculate a number to make things add up. If a figure is unreadable,
  set it to null — a null is better than a guessed value.
- Never change a VAT amount or a line amount just to force the items to equal the total.
  The total and the VAT come from the receipt as printed; reconciling them is NOT your job.

VAT SUMMARY TABLE -> "tax_lines" (THIS is the authoritative VAT — read it carefully):
- Near the total these receipts print a VAT/IVA summary table with one row per rate and
  columns like "%IVA | Total Liq. | IVA | Total" (sometimes "Taxa | Incidência | IVA | Total").
  Example row: "(A) 6,00%   2,44   0,15   2,59" meaning rate=6, net=2.44, vat=0.15, gross=2.59.
- Put ONE object in `tax_lines` per printed rate row, copying each printed number EXACTLY:
  `rate` = the % (6, 13, 23...), `net` = "Total Liq.", `vat` = "IVA", `gross` = "Total".
- Decimal comma: Portuguese prints "0,15" — output it as the number 0.15.
- Transcribe this table even if you also list the item lines. It is the VAT source of truth.
- Read EVERY rate row. A ticket may mix 6%, 13% and 23% — do not collapse them onto one
  rate or skip a row (a 23% line is easy to miss). The `gross` column must add up to the
  TOTAL A PAGAR. If your `tax_lines` gross does not sum to the total, you missed a row.

DISCOUNTS / SAVINGS — never treat these as products:
- Lines labelled "POUPANÇA", "DESCONTO", "Special Offer", "Promoção", "Total de descontos
  e poupanças", "CARTÃO CONTINENTE", or ANY amount shown as negative or in (parentheses)
  are SAVINGS, NOT a purchased item. Do NOT add them to `line_items` and do NOT give them
  their own VAT line.
- `total` is ALWAYS the final AMOUNT PAID after discounts (look for "Amount paid",
  "Total a pagar", "Total"). It is NOT the subtotal. So on a receipt like
  "Subtotal 32.38 / Special Offer (13.99) / Amount paid 18.39", set `total` = 18.39.
- Add up every discount and put the POSITIVE total in `discount_total` (here 13.99). The
  item lines (at full price) will sum ABOVE `total` by about that much — that is expected,
  so never shrink the items or invent a line to force them to equal the amount paid.

CATEGORY (you are already reading the receipt, so suggest where this expense belongs):
- Choose the single best-fit value for `category`, copied EXACTLY (same spelling and
  capitalisation) from this list:
  "Groceries", "Dining & Cafes", "Transport & Fuel", "Utilities", "Rent & Housing",
  "Software & Subscriptions", "Office & Supplies", "Travel", "Health & Pharmacy",
  "Entertainment", "Professional Services", "Taxes & Fees", "Tobacco", "Income".
- Judge from the vendor and the items. A supermarket / hypermarket (e.g. Continente,
  Pingo Doce, Lidl, Auchan) selling food and household goods is "Groceries". A sit-down
  meal or coffee is "Dining & Cafes". A fuel station is "Transport & Fuel". Cigarettes /
  tobacco (tabaco, cigarros) is "Tobacco".
- If nothing fits or you are unsure, set `category` to null — do NOT guess wildly.

ORIENTATION — DO THIS FIRST, BEFORE READING ANY VALUE:
- The photo is often rotated 90° (sideways) or 180° (upside down). You MUST fix the
  orientation in your mind BEFORE extracting anything — reading a sideways receipt is the
  #1 cause of wrong dates and VAT.
- Find the orientation using the receipt's layout: the STORE NAME / logo is at the TOP,
  the item list is in the MIDDLE, and the TOTAL and the date/time are near the BOTTOM.
  Text lines run horizontally and are read top-to-bottom.
- If the store name is NOT at the top with lines running left-to-right (e.g. the text
  runs vertically, or the logo is on the side/bottom), the image is rotated. Mentally
  rotate it 90°/180°/270° until the store name sits at the top and every line reads
  normally left-to-right. ONLY THEN read the fields.
- Double-check digits after rotating: a sideways "2026" or "13%" is easy to misread, so
  re-read the year and the VAT rows once the image is upright.

LINE ITEMS:
- Extract EVERY item row in the itemized section — one object per product line,
  including short receipts with only 2-3 items. Do NOT stop after the first item.
- The line items should add up to (or close to) the printed total; if your items
  fall far short of the total, you have likely missed some — look again.
- `amount` is the GROSS (VAT-inclusive) price for that line.
- ALWAYS set `quantity` to the number of units on that line: "2 x 0,79" -> quantity 2,
  "1x Média" -> quantity 1. A plain single item is quantity 1. Only use null if the
  count is genuinely unreadable — never leave it null when the quantity is visible.
- Do NOT invent a filler line (e.g. a tiny 0.01-0.05 row) just to make the items reach
  the total. List only real printed products; it is fine if they don't sum to the total.

PER-LINE VAT (important — these receipts can mix VAT rates on one ticket):
- Portuguese receipts tag each line with a VAT CODE (a letter like A/B/C or a number)
  and print a VAT SUMMARY table near the total mapping each code to a rate and base,
  e.g. "A 23%", "B 13%", "C 6%". Portuguese rates are 23, 13 and 6 (Madeira/Azores
  differ). Use that table to set each line's `vat_rate` to the correct percentage.
- If a line shows no code and no rate can be inferred, set its `vat_rate` to null.
- Put the per-line percentage (e.g. 23), NOT the VAT amount, in `vat_rate`. Keep the
  top-level `vat_rate`/`vat_amount` as the receipt's overall/summary figures.
- The "RESUMO DO IVA" / "IVA Liquidado" summary often lists TWO OR THREE DIFFERENT rates
  (e.g. a 6% row AND a 13% row — groceries/dairy at 6%, prepared food/gastronomia at 13%).
  Read EVERY row and give each its own rate. Do NOT collapse different rows onto 6%: if
  two lines have clearly different base/VAT amounts, they are almost certainly different
  rates. The rate code may appear in parentheses, e.g. "(11)"≈6%, "(14)"≈13%, "(23)"≈23%.

ESTIMATED VAT when the receipt prints NONE (e.g. Uber Eats, delivery, simple tills):
- If the receipt lists products but shows NO VAT table and NO per-line VAT codes, you MAY
  set each line's `vat_rate` to the STANDARD mainland-Portugal rate for that product type,
  and set top-level "vat_estimated": true. Typical rates:
    * Prepared / restaurant meals, pizza, cooked dishes, coffee or tea served: 13%
    * Bread and basic/essential groceries, fresh fruit & veg, milk: 6%
    * Soft drinks, bottled water, juices, alcohol, snacks/sweets, most other goods, and
      delivery/service fees: 23%
  (Madeira and the Azores use lower rates; adjust only if the receipt names those regions.)
- ONLY estimate when nothing is printed. If ANY VAT is printed (a summary table or line
  codes), read it and leave "vat_estimated" false — never override printed VAT with a guess.

DATE RULES (important — these receipts are European, from Portugal):
- The DOCUMENT date is printed near the TOP, by the invoice number (e.g.
  "Nro:FS BEB002/322839 05/10/2026 12:34" or next to "Fatura"/"Fatura Simplificada").
  Use THIS as the date. It is DAY-first "DD/MM/YYYY": "05/10/2026" -> "2026-10-05"
  (5 October, NOT 10 May, NOT the 26th).
- Printed dates are DAY-first, never US month-first. "03/10/2026" -> "2026-10-03".
- Some chains (e.g. Auchan/MyAuchan, Pingo Doce) label the date "Data Emissão" or
  "Data" and print it ISO YEAR-FIRST "YYYY-MM-DD" (e.g. "Data Emissão: 2026-10-13" =
  13 Oct 2026). When you see a four-digit year FIRST with dashes, read it as YYYY-MM-DD
  and trust it. Read all four year digits carefully: 2026, not 2021/2023.
- Tell the two date styles apart by PUNCTUATION, not position:
  * SLASHES "DD/MM/YYYY" (or DD/MM/YY) = the TOP document date, DAY-first. So
    "14/10/2026" = 14 Oct 2026, and "26/10/26" = 26 Oct 2026 (expand "26" -> 2026).
    Here the FIRST number is the day and CAN be up to 31.
  * DASHES "YY-MM-DD" = the BOTTOM card-terminal date, YEAR-first. So "26-10-14" =
    year 2026, month 10, day 14. Here the FIRST pair is the 2-digit year (20YY), NOT a
    day; the LAST pair is the day, NOT a year. "23-10-14" would be 2023 — but these are
    recent receipts, so a terminal year of 23/22 almost certainly means you misread it.
- Prefer the TOP slash date. Use the terminal dash date only if the top one is unreadable.
- Always output ISO "YYYY-MM-DD".
- SANITY CHECK (do this before answering): {today_line} A receipt is almost always from
  the last few days and is NEVER in the future. If your date comes out more than ~2
  months before today, or in a year other than the current one, you have misread a
  digit — RE-READ the year on the top line (a crumpled "2026" is easily misread as
  "2023"). Only output an old year if the printed digits are genuinely unambiguous.

Be conservative with confidence: if the image is blurry, cut off, rotated, or ambiguous, \
report a low value. Do not invent values you cannot read."""


def _build_prompt(today: datetime.date | None = None, note: str | None = None) -> str:
    """Fill the recency anchor into the prompt. Uses .replace (not .format) because
    the prompt contains literal JSON braces. An optional user `note` is appended as a
    hint (e.g. "the date is handwritten at the top", "this is a fuel receipt")."""
    today = today or datetime.date.today()
    line = f"today's date is {today.isoformat()}."
    prompt = EXTRACTION_PROMPT.replace("{today_line}", line)
    if note and note.strip():
        prompt += (
            "\n\nHINT FROM THE PERSON WHO UPLOADED THIS (use it to resolve ambiguity — "
            "e.g. which vendor, the correct date, or which number is the total — but still "
            f"READ the printed figures and never invent values): {note.strip()}"
        )
    return prompt


# Focused second pass used ONLY when the first date read looks wrong (future or very
# old). Asking for nothing but the date — with the full-image detail — lets the model
# concentrate on the one field it fumbled instead of juggling the whole receipt.
DATE_REREAD_PROMPT = """Look at this Portuguese receipt and read ONLY its date.
Return ONLY a JSON object: {"date": "YYYY-MM-DD" | null}.

- The document date is near the TOP, by the invoice number ("Fatura"/"Nro:FS ..."),
  printed DAY-first with SLASHES: "14/10/2026" = 14 Oct 2026. The first number is the day.
- Some chains label it "Data Emissão"/"Data" and print it ISO YEAR-first "YYYY-MM-DD"
  (e.g. "Data Emissão: 2026-10-13" = 13 Oct 2026). Read all four year digits (2026).
- There is also a card-terminal date near the bottom with DASHES, YEAR-first:
  "26-10-14" = 2026-10-14 (the leading "26" is the year 2026, not a day).
- The photo may be ROTATED/sideways — rotate it mentally so the text is upright first.
- For reference, {today_line} This receipt is recent — within the last few days, NEVER in
  the future. If you are about to output a year other than the current one, you have
  misread the year digits (a crumpled "2026" often looks like "2023") — re-read them.
- Read the digits that are actually printed. If you truly cannot read the date, return null."""


def _parse_iso_date(raw: Any) -> datetime.date | None:
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def reread_date(
    image_bytes: bytes,
    filename: str | None,
    settings: Settings,
    today: datetime.date | None = None,
) -> datetime.date | None:
    """Re-read just the date with a focused prompt. Returns a date only if it is
    plausible (not in the future, not absurdly old); otherwise None so the caller
    keeps the original reading. Never raises — a failed re-read is a no-op."""
    today = today or datetime.date.today()
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return None  # mock has no real image to re-read; don't fabricate a date
    media_type = _guess_media_type(filename, image_bytes)
    prompt = DATE_REREAD_PROMPT.replace("{today_line}", f"today's date is {today.isoformat()}.")
    try:
        if provider == "openai":
            payload, _ = _extract_openai(image_bytes, media_type, settings, prompt, kind="date_reread")
        elif provider == "anthropic":
            payload, _ = _extract_anthropic(image_bytes, media_type, settings, prompt, kind="date_reread")
        elif provider == "ollama":
            payload, _ = _extract_ollama(image_bytes, media_type, settings, prompt, kind="date_reread")
        else:
            return None
    except Exception:  # noqa: BLE001 - re-read is best-effort
        return None
    d = _parse_iso_date(payload.get("date"))
    if d is None or d > today or (today - d).days > 366:
        return None
    return d


def _exif_orient(image_bytes: bytes) -> tuple[bytes, bool]:
    """Apply the photo's EXIF orientation (fixes phone photos stored sideways) and
    report whether the result is landscape (likely a sideways receipt). Re-encodes to
    JPEG. Returns the original bytes + False if Pillow is unavailable or the image
    can't be read."""
    if not _PIL_OK:
        return image_bytes, False
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))
        w, h = img.size
        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue(), (w > h * 1.1)
    except Exception:  # noqa: BLE001
        return image_bytes, False


def _rotate(image_bytes: bytes, degrees: int) -> bytes:
    """Rotate the image `degrees` CLOCKWISE (90/180/270). Best-effort."""
    if not _PIL_OK or not degrees:
        return image_bytes
    try:
        img = Image.open(io.BytesIO(image_bytes)).rotate(-degrees, expand=True)
        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return image_bytes


def _read_score(r: ExtractionResult) -> float:
    """Heuristic 'how upright/correct does this read look' score. A correctly oriented
    receipt reads a total + vendor confidently AND reconciles (items or the printed VAT
    table sum to the total). A sideways read usually fails one of these."""
    s = 0.0
    total = r.total or 0.0
    if total > 0:
        s += 3.0
    if r.vendor:
        s += 2.0
    if r.date:
        s += 1.0
    s += float(r.confidence or 0.0)
    if total > 0:
        tol = max(0.5, 0.05 * total)
        items = [li.amount for li in r.line_items if li.amount]
        if items and abs(sum(items) - total) <= tol:
            s += 2.0
        if r.tax_lines:
            tl_gross = sum(
                (tl.gross if tl.gross is not None else (tl.net or 0) + (tl.vat or 0))
                for tl in r.tax_lines
            )
            if abs(tl_gross - total) <= tol:
                s += 2.0
    # Reward COMPLETENESS: a correctly-oriented read captures more of the printed
    # structure (every VAT-summary row, more item lines). A sideways read often
    # reconciles internally on a FRAGMENT (e.g. a single line read as the whole
    # receipt), so the number of reconciling rows is what separates the full read
    # from a self-consistent fragment that lands on the same `total`.
    s += min(len(r.tax_lines), 4) * 0.5
    s += min(len(r.line_items), 8) * 0.2
    return s


# Below this, a portrait read is suspect enough to also try an upside-down (180°) pass.
_WEAK_SCORE = 5.0


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


def _extract_anthropic(
    image_bytes: bytes, media_type: str, settings: Settings, prompt: str, kind: str = "receipt_extract"
) -> tuple[dict[str, Any], LlmCall]:
    import anthropic

    client = wrap_anthropic_if_enabled(anthropic.Anthropic(api_key=settings.anthropic_api_key))
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]

    # Structured output first (see _extract_openai); raw parse is the fallback.
    started = time.perf_counter()
    try:
        import instructor

        ic = instructor.from_anthropic(client)
        obj, raw = ic.messages.create_with_completion(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            response_model=ExtractionResult,
            max_retries=settings.instructor_max_retries,
            messages=messages,
        )
        call = LlmCall.timed(
            provider="anthropic", model=settings.anthropic_model, kind=kind, started=started, resp=raw
        )
        return obj.model_dump(mode="json"), call
    except Exception:  # noqa: BLE001 - structured mode unavailable/failed -> raw fallback
        pass

    started = time.perf_counter()
    resp = client.messages.create(
        model=settings.anthropic_model, max_tokens=settings.anthropic_max_tokens, messages=messages
    )
    call = LlmCall.timed(
        provider="anthropic", model=settings.anthropic_model, kind=kind, started=started, resp=resp, fell_back=True
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
    return _parse_json_payload(text), call


def _is_reasoning_model(model: str) -> bool:
    """Reasoning models (gpt-5*, o1/o3/o4*) use `max_completion_tokens` (not
    `max_tokens`) and spend part of that budget on hidden reasoning. They read a
    dense/fiddly VAT table far more reliably than gpt-4o, so we give them room."""
    m = model.lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def _extract_openai(
    image_bytes: bytes, media_type: str, settings: Settings, prompt: str, kind: str = "receipt_extract"
) -> tuple[dict[str, Any], LlmCall]:
    from openai import OpenAI

    client = wrap_openai_if_enabled(OpenAI(api_key=settings.openai_api_key))
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    # Reasoning models need the completion-token param + a budget big enough to
    # cover the reasoning tokens before the JSON (1024 would often return empty).
    token_arg = (
        {"max_completion_tokens": 8000}
        if _is_reasoning_model(settings.openai_model)
        else {"max_tokens": 1024}
    )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    # "high" detail = full-resolution tiling. Much better OCR on
                    # dense, crumpled, or rotated receipts (worth the extra tokens).
                    "image_url": {"url": f"data:{media_type};base64,{b64}", "detail": "high"},
                },
            ],
        }
    ]

    # Structured output first: Instructor validates the model's JSON against
    # ExtractionResult and re-prompts (up to instructor_max_retries) on a schema
    # violation. On ANY failure — including structured mode being unsupported for
    # this model — fall back to a plain call + tolerant parse (the previous
    # behaviour) and flag fell_back on the trace. This keeps the accuracy-critical
    # path safe while giving us validated output + a measurable fallback rate.
    started = time.perf_counter()
    try:
        import instructor

        ic = instructor.from_openai(client)
        obj, raw = ic.chat.completions.create_with_completion(
            model=settings.openai_model,
            response_model=ExtractionResult,
            max_retries=settings.instructor_max_retries,
            **token_arg,
            messages=messages,
        )
        call = LlmCall.timed(
            provider="openai", model=settings.openai_model, kind=kind, started=started, resp=raw
        )
        return obj.model_dump(mode="json"), call
    except Exception:  # noqa: BLE001 - structured mode unavailable/failed -> raw fallback
        pass

    started = time.perf_counter()
    resp = client.chat.completions.create(model=settings.openai_model, **token_arg, messages=messages)
    call = LlmCall.timed(
        provider="openai", model=settings.openai_model, kind=kind, started=started, resp=resp, fell_back=True
    )
    return _parse_json_payload(resp.choices[0].message.content or "{}"), call


def _extract_ollama(
    image_bytes: bytes, media_type: str, settings: Settings, prompt: str, kind: str = "receipt_extract"
) -> tuple[dict[str, Any], LlmCall]:
    """Local, on-device read via Ollama's OpenAI-compatible endpoint — the receipt
    image never leaves the machine (the privacy-first option for personal financial
    data). Needs a VISION model pulled locally (e.g. `ollama pull qwen2.5vl:7b`) and
    no API key. Mirrors `_extract_openai`: structured output via Instructor (JSON mode,
    which local models support more reliably than tool-calling) with the same tolerant
    raw-parse fallback — local models fail schema more often, so the fallback matters
    more here. Cost is $0 (price_usd returns 0 for an unknown/local model)."""
    from openai import OpenAI

    # api_key is required by the SDK but ignored by Ollama; base_url points at the
    # local server. NOT wrapped for LangSmith — this path exists precisely to keep
    # data local, so it must never be shipped to a hosted tracer.
    client = OpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            ],
        }
    ]

    started = time.perf_counter()
    try:
        import instructor

        ic = instructor.from_openai(client, mode=instructor.Mode.JSON)
        obj, raw = ic.chat.completions.create_with_completion(
            model=settings.ollama_model,
            response_model=ExtractionResult,
            max_retries=settings.instructor_max_retries,
            max_tokens=4096,
            messages=messages,
        )
        call = LlmCall.timed(
            provider="ollama", model=settings.ollama_model, kind=kind, started=started, resp=raw
        )
        return obj.model_dump(mode="json"), call
    except Exception:  # noqa: BLE001 - structured mode unavailable/failed -> raw fallback
        pass

    started = time.perf_counter()
    resp = client.chat.completions.create(
        model=settings.ollama_model, max_tokens=4096, messages=messages
    )
    call = LlmCall.timed(
        provider="ollama", model=settings.ollama_model, kind=kind, started=started, resp=resp, fell_back=True
    )
    return _parse_json_payload(resp.choices[0].message.content or "{}"), call


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
        # Printed VAT summary table (authoritative). Gross ties to the 12.30 total.
        "tax_lines": [
            {"rate": 6, "net": 2.00, "vat": 0.12, "gross": 2.12},
            {"rate": 23, "net": 8.28, "vat": 1.90, "gross": 10.18},
        ],
        "category": "Groceries",
        "confidence": 0.5,
    }


def _to_result(payload: dict[str, Any]) -> ExtractionResult:
    """Coerce a provider payload into the validated model; tolerate missing keys."""
    return ExtractionResult(
        vendor=payload.get("vendor"),
        date=payload.get("date") or None,
        total=payload.get("total"),
        vat_amount=payload.get("vat_amount"),
        vat_rate=payload.get("vat_rate"),
        currency=payload.get("currency"),
        line_items=payload.get("line_items") or [],
        tax_lines=payload.get("tax_lines") or [],
        discount_total=payload.get("discount_total"),
        vat_estimated=bool(payload.get("vat_estimated")),
        category=payload.get("category") or None,
        confidence=float(payload.get("confidence") or 0.0),
    )


def _extract_once(
    image_bytes: bytes, media_type: str, provider: str, settings: Settings, prompt: str
) -> tuple[dict[str, Any], LlmCall]:
    if provider == "anthropic":
        return _extract_anthropic(image_bytes, media_type, settings, prompt)
    if provider == "openai":
        return _extract_openai(image_bytes, media_type, settings, prompt)
    if provider == "ollama":
        return _extract_ollama(image_bytes, media_type, settings, prompt)
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")


def extract_receipt(
    image_bytes: bytes,
    filename: str | None,
    settings: Settings,
    note: str | None = None,
) -> tuple[ExtractionResult, bytes, dict[str, Any]]:
    """Extract a receipt, auto-correcting orientation server-side.

    Returns (result, oriented_bytes, trace). We first apply the photo's EXIF
    orientation, then — because a sideways receipt is the top cause of misread
    dates/VAT — try rotating the pixels and keep the read that looks most
    upright/correct (by `_read_score`). `oriented_bytes` is the image of the chosen
    orientation, so the caller can store the straightened receipt. `trace` is an
    observability record aggregating every orientation read made (latency, tokens,
    estimated cost); the caller persists it. Pillow-optional: without it we do a
    single read of the original image.
    """
    provider = settings.llm_provider.lower()
    if provider == "mock":
        trace = aggregate([LlmCall(provider="mock", model="mock")], provider="mock", model="mock", kind="receipt_extract")
        return _to_result(_extract_mock(image_bytes, filename)), image_bytes, trace

    if provider == "anthropic":
        model = settings.anthropic_model
    elif provider == "ollama":
        model = settings.ollama_model
    else:
        model = settings.openai_model
    prompt = _build_prompt(note=note)
    oriented, landscape = _exif_orient(image_bytes)
    media_type = _guess_media_type(filename if not _PIL_OK else "r.jpg", oriented)

    # Candidate rotations. A landscape photo is almost certainly a sideways (or
    # upside-down) receipt, so try ALL four orientations and keep the best-reading
    # one; a portrait photo usually needs none.
    angles = [90, 270, 180, 0] if (_PIL_OK and landscape) else [0]

    calls: list[LlmCall] = []
    best: tuple[float, ExtractionResult, bytes] | None = None
    for angle in angles:
        candidate = _rotate(oriented, angle) if angle else oriented
        try:
            payload, call = _extract_once(candidate, media_type, provider, settings, prompt)
        except Exception:  # noqa: BLE001 - a bad rotation shouldn't kill the whole read
            continue
        calls.append(call)
        result = _to_result(payload)
        score = _read_score(result)
        if best is None or score > best[0]:
            best = (score, result, candidate)
        # NO early break: a sideways read can look 'strong' (confident + internally
        # consistent on a fragment), so stopping at the first plausible orientation
        # would miss the genuinely upright one. We try every candidate and keep the
        # most complete/reconciling read (see _read_score).

    # Portrait but the best read is weak -> it may be upside down; try one 180° pass.
    if _PIL_OK and not landscape and best is not None and best[0] < _WEAK_SCORE:
        try:
            flipped = _rotate(oriented, 180)
            payload, call = _extract_once(flipped, media_type, provider, settings, prompt)
            calls.append(call)
            r = _to_result(payload)
            if _read_score(r) > best[0]:
                best = (_read_score(r), r, flipped)
        except Exception:  # noqa: BLE001
            pass

    if best is None:
        # Every attempt errored — surface a normal read of the oriented image so the
        # caller still gets a (failing) result or a raised provider error.
        payload, call = _extract_once(oriented, media_type, provider, settings, prompt)
        calls.append(call)
        trace = aggregate(calls, provider=provider, model=model, kind="receipt_extract")
        return _to_result(payload), oriented, trace
    trace = aggregate(calls, provider=provider, model=model, kind="receipt_extract")
    return best[1], best[2], trace
