"""Parse an uploaded bank-statement PDF into normalized transaction dicts.

A fallback for when the user can't export a CSV. Two paths, both ending in the
SAME normalized rows that `csv_import.parse_bank_csv` produces, so everything
downstream (reconciliation, exceptions, close) is identical:

1. Deterministic text extraction with `pdfplumber` (local, free, no network).
2. Structuring the extracted text into transactions:
   - with a real LLM provider, gpt-4o *reads* the text into {date, description,
     amount} rows (it never does math — amounts/dates are re-parsed in code,
     consistent with D1 "the AI is never trusted blindly");
   - a deterministic **regex heuristic** handles the common
     "DATE  DESCRIPTION  AMOUNT [BALANCE]" layout and is the offline/mock
     fallback (and the safety net if the model call fails).

Amounts are normalized to SIGNED values (negative = money out), matching
csv_import. Scanned/image-only PDFs (no extractable text) raise a clear error —
we don't silently guess at pixels here; the user can upload a CSV instead.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any

from ..config import Settings
from . import monitoring
from .csv_import import _parse_date, _parse_money
from .redaction import redact_sensitive

try:  # pdfplumber is optional — the endpoint reports a clear error if absent.
    import pdfplumber

    _PDF_OK = True
except Exception:  # noqa: BLE001
    _PDF_OK = False


class PdfImportError(Exception):
    """Raised with a user-facing message when a PDF can't be turned into rows."""


# --- 1. text extraction -----------------------------------------------------

def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Pull the text layer out of a PDF. Empty string = a scanned/image PDF."""
    if not _PDF_OK:
        raise PdfImportError(
            "PDF support isn't installed on the server (pip install pdfplumber)."
        )
    parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
    except Exception as exc:  # noqa: BLE001
        raise PdfImportError(f"Could not read the PDF: {exc}") from exc
    return "\n".join(parts).strip()


# --- 2a. deterministic heuristic parse --------------------------------------

# A statement line usually starts with a date and ends with one or two money
# figures (amount, optionally a running balance). We match day-first slash/dot
# dates and ISO dates; the description is whatever sits between.
_DATE = r"(?:\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}-\d{2}-\d{2})"
_MONEY = r"[-+]?\(?\d[\d.,]*\)?-?"
_LINE_RE = re.compile(
    rf"^\s*(?P<date>{_DATE})\s+(?P<desc>.*?)\s+(?P<nums>{_MONEY}(?:\s+{_MONEY})?)\s*$"
)


def _signed_money(token: str) -> float | None:
    """Parse one money token, honouring accounting-negative conventions that
    `_parse_money` doesn't: "(12,34)" and a trailing minus "12,34-" are both
    money OUT (negative)."""
    token = token.strip()
    if not token:
        return None
    negative = False
    if token.startswith("(") and token.endswith(")"):
        negative, token = True, token[1:-1]
    if token.endswith("-"):
        negative, token = True, token[:-1]
    val = _parse_money(token)
    if val is None:
        return None
    return -abs(val) if negative else val


def parse_lines_heuristic(text: str, date_format: str | None = None) -> list[dict[str, Any]]:
    """Regex fallback: one transaction per matching line. When a line ends in two
    numbers, the first is the amount and the second the running balance."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        nums = m.group("nums").split()
        amount = _signed_money(nums[0])
        if amount is None:
            continue
        txn_date = _parse_date(m.group("date"), date_format)
        if txn_date is None:
            continue  # never store an undated transaction
        balance = _signed_money(nums[1]) if len(nums) > 1 else None
        rows.append(
            {
                "txn_date": txn_date,
                "description": (m.group("desc") or "").strip() or None,
                "amount": round(amount, 2),
                "balance": balance,
                "raw": {"line": line.strip()},
            }
        )
    return rows


# --- 2b. LLM structuring -----------------------------------------------------

_LLM_PROMPT = """You are reading the plain text of a bank-statement PDF. Return ONLY a JSON
object (no prose, no markdown fences): {"transactions": [ {"date": "YYYY-MM-DD",
"description": string, "amount": number, "balance": number|null } ]}.

Rules:
- One object per transaction ROW. Ignore headers, footers, page numbers, opening/closing
  balance summary lines, and marketing text — list only real dated movements.
- "amount" is SIGNED: money OUT (debit, payment, withdrawal, purchase) is NEGATIVE; money
  IN (credit, deposit, salary, refund) is POSITIVE. Statements show this via a debit/credit
  column, a sign, parentheses "(12,34)", a trailing "D"/"C", or the running balance going
  down/up — use whatever the statement makes clear.
- Dates are European DAY-first ("05/10/2026" = 5 Oct 2026). Output ISO "YYYY-MM-DD".
- Decimal comma: "1.234,56" means 1234.56. Output plain JSON numbers (1234.56).
- Transcribe the printed figures; do not invent or adjust any number. If a row's amount is
  unreadable, skip that row rather than guessing.
"""


def _structure_with_llm(text: str, settings: Settings, note: str | None = None) -> list[dict[str, Any]]:
    """Ask the configured LLM to turn statement text into raw transaction dicts.
    Text-only (cheap). Raises on any provider/parse error so the caller can fall
    back to the heuristic. `note` is an optional hint from the user."""
    provider = settings.llm_provider.lower()
    prompt = _LLM_PROMPT
    if note and note.strip():
        prompt += (
            f"\nHINT FROM THE USER (use it to resolve ambiguity, but never invent "
            f"figures): {note.strip()}\n"
        )
    # Data minimisation: mask IBANs / card numbers before the statement text leaves
    # the machine. The structuring only needs date/description/amount, so redacting
    # account identifiers costs nothing and keeps them out of the provider's hands.
    prompt += "\nBANK STATEMENT TEXT:\n" + redact_sensitive(text)
    if provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.openai_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        content = resp.choices[0].message.content or "{}"
    elif provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        content = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
    else:
        raise ValueError(f"LLM structuring unavailable for provider {provider!r}")

    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lstrip().lower().startswith("json"):
            content = content.lstrip()[4:]
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end != -1:
        content = content[start : end + 1]
    data = json.loads(content)
    return data.get("transactions") or []


def normalize_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-parse LLM/structured rows in code (dates + money), dropping anything
    without a usable amount. Mirrors csv_import's output shape exactly."""
    rows: list[dict[str, Any]] = []
    for r in raw_rows:
        amount = _signed_money(str(r.get("amount"))) if r.get("amount") is not None else None
        if amount is None:
            continue
        txn_date = _parse_date(str(r.get("date") or ""), None)
        if txn_date is None:
            continue  # never store an undated transaction
        balance_raw = r.get("balance")
        balance = _signed_money(str(balance_raw)) if balance_raw is not None else None
        rows.append(
            {
                "txn_date": txn_date,
                "description": (str(r.get("description")) if r.get("description") else "").strip()
                or None,
                "amount": round(amount, 2),
                "balance": balance,
                "raw": r,
            }
        )
    return rows


# --- top-level entry points --------------------------------------------------

def parse_statement_text(
    text: str, settings: Settings, note: str | None = None
) -> list[dict[str, Any]]:
    """Turn already-extracted statement text into normalized rows. Prefers the
    LLM when a real provider is configured; always falls back to the heuristic."""
    if not text.strip():
        raise PdfImportError(
            "No text found in the PDF — it looks scanned (an image). "
            "Please upload a CSV, or a text-based PDF exported from your bank."
        )

    provider = settings.llm_provider.lower()
    if provider in ("openai", "anthropic") and settings.llm_configured:
        try:
            rows = normalize_rows(_structure_with_llm(text, settings, note))
            if rows:
                return rows
        except Exception as exc:  # noqa: BLE001 - fall back to the deterministic parse
            monitoring.capture(exc, surface="pdf_import.llm_structuring")

    return parse_lines_heuristic(text)


def parse_bank_pdf(
    pdf_bytes: bytes, settings: Settings, note: str | None = None
) -> list[dict[str, Any]]:
    """Full path: extract text from the PDF, then structure it into rows."""
    return parse_statement_text(extract_pdf_text(pdf_bytes), settings, note)
