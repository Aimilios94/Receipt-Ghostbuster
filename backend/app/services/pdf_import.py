"""Parse an uploaded bank-statement PDF into normalized transaction dicts.

A fallback for when the user can't export a CSV. Two paths, both ending in the
SAME normalized rows that `csv_import.parse_bank_csv` produces, so everything
downstream (reconciliation, exceptions, close) is identical:

1. Deterministic text extraction with `pdfplumber` (local, free, no network).
2. Structuring the extracted text into transactions:
   - a **Revolut statement** is read in code. It is accepted only if every row and the
     totals reconcile to the statement's own printed summary, so it needs no model
     and no statement text leaves the machine;
   - any other PDF goes to a real LLM provider, which *reads* the text into {date,
     description, amount} rows (it never does math — amounts/dates are re-parsed in
     code, consistent with D1 "the AI is never trusted blindly");
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
import unicodedata
from typing import Any

from ..config import Settings
from . import monitoring
from .csv_import import _parse_date, _parse_money
from .extraction import _is_reasoning_model
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


# --- 2b. Revolut statements, read in code ------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "fev": 2, "abr": 4, "mai": 5, "ago": 8, "set": 9, "out": 10, "dez": 12,
    "ιαν": 1, "φεβ": 2, "μαρ": 3, "απρ": 4, "μαι": 5, "ιουν": 6,
    "ιουλ": 7, "αυγ": 8, "σεπ": 9, "οκτ": 10, "νοε": 11, "δεκ": 12,
}
_EURO = r"(?:€\s?[\d.,]+|[\d.,]+\s?€)"
_REVOLUT_ROW = re.compile(
    rf"^(?P<day>\d{{1,2}})\s+(?P<month>\S+)\s+(?P<year>\d{{4}})\s+(?P<desc>.+?)\s+"
    rf"(?P<amount>{_EURO})\s+(?P<balance>{_EURO})$"
)
_REVOLUT_TOTALS = re.compile(
    rf"^(?:Total|Σύνολο)\s+(?P<opening>{_EURO})\s+(?P<out>{_EURO})\s+(?P<in>{_EURO})\s+(?P<closing>{_EURO})$"
)
# Sections after the completed transactions list movements that never settled.
_REVOLUT_STOP = re.compile(r"^(?:Reverted|Αντιστράφηκε|Pending|Σε εκκρεμότητα)\b", re.IGNORECASE)
_CARD_DETAIL = ("card:", "κάρτα:", "cartão:")
_REFERENCE_DETAIL = ("reference:", "αναφορά:", "referência:")
_COUNTERPARTY_DETAIL = ("to:", "from:", "προς:", "από:", "para:", "de:")
_TOP_UP = re.compile(r"top-up|προσθήκη", re.IGNORECASE)
# Greek rows take the English wording, so reconciliation, the breakdown and the chatbot
# treat a statement the same in either language. The original stays in `raw`.
_GREEK_PREFIXES = (
    ("Μεταφορά προς ", "Transfer to "),
    ("Μεταφορά από ", "Transfer from "),
    ("Προσθήκη Google Pay από ", "Google Pay top-up by "),
)
_CENT = 0.005  # float rounding only: the figures must match to the cent


def _month_number(token: str) -> int | None:
    plain = "".join(
        c for c in unicodedata.normalize("NFD", token.lower()) if not unicodedata.combining(c)
    ).strip(".")
    return _MONTHS.get(plain[:4]) or _MONTHS.get(plain[:3])


def _revolut_type(description: str, details: list[str]) -> str | None:
    lowered = [d.strip().lower() for d in details]
    if any(d.startswith(_CARD_DETAIL) for d in lowered):
        return "Card Payment"
    if _TOP_UP.search(description):
        return "Topup"
    if any(d.startswith(_REFERENCE_DETAIL) for d in lowered):
        return "Transfer"
    return None


def _revolut_counterparty(details: list[str]) -> str | None:
    """The transfer's named recipient or sender. The IBAN after the comma is dropped."""
    for line in details:
        label, sep, value = line.strip().partition(":")
        if sep and f"{label.lower()}:" in _COUNTERPARTY_DETAIL:
            return value.split(",")[0].strip() or None
    return None


def parse_revolut_statement(text: str) -> list[dict[str, Any]]:
    """Read a Revolut statement in code, or return [] so another path can try.

    The money columns aren't signed, so direction comes from the running balance. The
    result is only trusted if every row moves the balance by its own amount and the
    totals equal the statement's printed summary.
    """
    if "revolut" not in text.lower():
        return []
    lines = text.splitlines()
    totals = next((m for m in map(_REVOLUT_TOTALS.match, lines) if m), None)
    if not totals:
        return []
    opening, printed_out, printed_in, closing = (
        _parse_money(totals.group(k)) for k in ("opening", "out", "in", "closing")
    )

    rows: list[dict[str, Any]] = []
    details: list[list[str]] = []
    balance = opening
    total_out = total_in = 0.0
    for line in lines:
        if _REVOLUT_STOP.match(line.strip()):
            break
        m = _REVOLUT_ROW.match(line.strip())
        if not m:
            if details:
                details[-1].append(line)
            continue
        month = _month_number(m.group("month"))
        amount = _parse_money(m.group("amount"))
        new_balance = _parse_money(m.group("balance"))
        if month is None or amount is None or new_balance is None:
            return []
        change = round(new_balance - balance, 2)
        if abs(abs(change) - amount) > _CENT:
            return []
        balance = new_balance
        if change < 0:
            total_out += amount
        else:
            total_in += amount
        original = m.group("desc").strip()
        description = original
        for greek, english in _GREEK_PREFIXES:
            if original.startswith(greek):
                description = english + original[len(greek):]
                break
        rows.append({
            "txn_date": f"{m.group('year')}-{month:02d}-{int(m.group('day')):02d}",
            "description": description,
            "amount": -amount if change < 0 else amount,
            "balance": new_balance,
            "raw": {"Date": f"{m.group('day')} {m.group('month')} {m.group('year')}", "Description": original},
        })
        details.append([])

    reconciles = (
        rows
        and abs(balance - closing) <= _CENT
        and abs(total_out - printed_out) <= _CENT
        and abs(total_in - printed_in) <= _CENT
    )
    if not reconciles:
        return []
    for row, row_details in zip(rows, details):
        kind = _revolut_type(row["raw"]["Description"], row_details)
        if kind:
            row["raw"]["Type"] = kind
        counterparty = _revolut_counterparty(row_details) if kind == "Transfer" else None
        if counterparty:
            row["raw"]["Counterparty"] = counterparty
    return rows


# --- 2c. LLM structuring -----------------------------------------------------

_LLM_PROMPT = """You are reading the plain text of a bank-statement PDF. Return ONLY a JSON
object (no prose, no markdown fences): {"transactions": [ {"date": "YYYY-MM-DD",
"description": string, "amount": number, "balance": number|null } ]}.

Rules:
- One object per transaction ROW. Ignore headers, footers, page numbers, opening/closing
  balance summary lines, and marketing text — list only real dated movements.
- The statement may be in any language. List completed movements only: skip any section of
  reversed, reverted, declined or pending items.
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
        # Reasoning models reject max_tokens and spend part of the budget on hidden
        # reasoning, and a month of rows is long.
        token_arg = (
            {"max_completion_tokens": 16000}
            if _is_reasoning_model(settings.openai_model)
            else {"max_tokens": 4096}
        )
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            **token_arg,
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
    """Turn already-extracted statement text into normalized rows. A Revolut statement
    that reconciles is read in code. Otherwise prefers the LLM when a real provider is
    configured, and always falls back to the heuristic."""
    if not text.strip():
        raise PdfImportError(
            "No text found in the PDF — it looks scanned (an image). "
            "Please upload a CSV, or a text-based PDF exported from your bank."
        )

    revolut_rows = parse_revolut_statement(text)
    if revolut_rows:
        return revolut_rows

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
