"""Parse an uploaded bank-statement CSV into normalized transaction dicts.

Configurable column mapping (see models.ColumnMapping), but it also AUTO-DETECTS
the usual column names (date/amount/description/balance, in a few languages and
debit/credit variants) so a standard bank export works without the user mapping
anything. Handles either a single signed `amount` column or separate debit/credit
columns. Amounts are normalized to SIGNED values (negative = money out). Pure
function — no DB, no network.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from ..models import ColumnMapping

_COMMON_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d.%m.%y",
)

# Header aliases, lower-cased, used when the mapping's column name isn't present.
# Covers English + Portuguese/Spanish/German exports (this app is used in Portugal).
_ALIASES: dict[str, tuple[str, ...]] = {
    "date": (
        "date", "transaction date", "txn date", "completed date", "date completed",
        "value date", "posting date", "booking date", "settlement date",
        "started date", "date started",
        "data", "data mov.", "data movimento", "data valor", "data de conclusão",
        "datum", "fecha", "fecha operación", "fecha valor",
    ),
    "state": ("state", "status", "estado", "situação"),
    "amount": (
        "amount", "value", "montante", "valor", "importe", "betrag", "import",
        "transaction amount", "amount (eur)", "montant",
    ),
    "description": (
        "description", "descricao", "descrição", "descrição do movimento",
        "memo", "details", "detail", "concept", "concepto", "narrative",
        "payee", "reference", "referência", "verwendungszweck", "buchungstext",
    ),
    "balance": ("balance", "saldo", "running balance", "kontostand", "saldo contabilístico"),
    "debit": ("debit", "debito", "débito", "money out", "withdrawal", "levantamento", "soll"),
    "credit": ("credit", "credito", "crédito", "money in", "deposit", "deposito", "haben"),
}


class CsvImportError(Exception):
    """Raised with a user-facing message when a CSV can't be turned into rows."""


def _parse_date(value: str, explicit_format: str | None) -> str | None:
    """Return an ISO date, or None if the value can't be parsed (so a blank/garbage
    cell never reaches the DB as an empty string)."""
    value = (value or "").strip()
    if not value:
        return None
    if explicit_format:
        try:
            return datetime.strptime(value, explicit_format).date().isoformat()
        except ValueError:
            return None
    # Drop any trailing time component ("2/10/2026 18:09" / "2026-10-05T10:00").
    value = value.replace("T", " ").split(" ")[0]
    for fmt in _COMMON_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    # Last resort: an already-ISO-looking prefix (e.g. "2026-10-05T..." ).
    head = value[:10]
    try:
        datetime.strptime(head, "%Y-%m-%d")
        return head
    except ValueError:
        return None


def _parse_money(value: str | None) -> float | None:
    if value is None:
        return None
    s = value.strip().replace("€", "").replace("$", "")
    if not s:
        return None
    # Normalize European "1.234,56" and thousands separators.
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    s = s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def _resolve_columns(headers: list[str], mapping: ColumnMapping) -> dict[str, str | None]:
    """Decide which actual CSV header backs each of our fields. Prefer the mapping's
    name when it's really in the file; otherwise fall back to known aliases."""
    present = {(h or "").strip().lower(): (h or "").strip() for h in headers}

    def pick(field: str, configured: str | None, use_aliases: bool = True) -> str | None:
        if configured and configured.strip().lower() in present:
            return configured.strip().lower()
        if use_aliases:
            for alias in _ALIASES.get(field, ()):  # first alias that exists wins
                if alias in present:
                    return alias
        return None

    # Only honour debit/credit if the mapping asked for them OR the file clearly has them.
    debit = pick("debit", mapping.debit)
    credit = pick("credit", mapping.credit)
    return {
        "date": pick("date", mapping.date),
        "amount": pick("amount", mapping.amount),
        "description": pick("description", mapping.description),
        "balance": pick("balance", mapping.balance),
        "state": pick("state", None),
        "debit": debit,
        "credit": credit,
    }


# Statement rows in these states haven't actually moved money (yet) — don't import
# them, or they'd create false "unmatched" exceptions during reconciliation.
_NON_FINAL_STATES = {
    "pending", "reverted", "declined", "failed", "cancelled", "canceled",
    "rejected", "void", "voided", "reversed",
}


def parse_bank_csv(content: str, mapping: ColumnMapping) -> list[dict[str, Any]]:
    # Sniff the delimiter so ';'-separated European exports also work.
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    headers = [h for h in (reader.fieldnames or []) if h is not None]
    cols = _resolve_columns(headers, mapping)

    header_list = ", ".join(h.strip() for h in headers if h.strip()) or "(none found)"
    if not cols["date"]:
        raise CsvImportError(
            f"Couldn't find a date column. The CSV headers are: {header_list}. "
            "Rename the date column to 'date', or export a statement that includes one."
        )
    if not (cols["amount"] or cols["debit"] or cols["credit"]):
        raise CsvImportError(
            f"Couldn't find an amount column. The CSV headers are: {header_list}. "
            "Expected an 'amount' column (or separate 'debit'/'credit' columns)."
        )

    rows: list[dict[str, Any]] = []
    amount_rows = 0           # rows that had a parseable amount
    dated_rows = 0            # of those, how many had a parseable date
    for raw in reader:
        lookup = {(k or "").strip().lower(): v for k, v in raw.items()}

        def col(name: str | None):
            return lookup.get(name) if name else None

        # Skip not-yet-settled rows (Revolut PENDING/REVERTED, etc.).
        if cols["state"]:
            state = (col(cols["state"]) or "").strip().lower()
            if state in _NON_FINAL_STATES:
                continue

        if cols["debit"] or cols["credit"]:
            debit = _parse_money(col(cols["debit"])) or 0.0
            credit = _parse_money(col(cols["credit"])) or 0.0
            amount = credit - debit if (debit or credit) else None  # credit (+), debit (-)
        else:
            amount = _parse_money(col(cols["amount"]))

        if amount is None:
            continue  # header repeats / summary rows with no amount
        amount_rows += 1

        txn_date = _parse_date(col(cols["date"]) or "", mapping.date_format)
        if txn_date is None:
            continue  # a row we can't date reliably — skip rather than store a bad date
        dated_rows += 1

        rows.append(
            {
                "txn_date": txn_date,
                "description": (col(cols["description"]) or "").strip() or None,
                "amount": round(amount, 2),
                "balance": _parse_money(col(cols["balance"])),
                "raw": raw,
            }
        )

    if amount_rows and not dated_rows:
        raise CsvImportError(
            "Found transactions but couldn't read their dates. If the dates use an "
            "unusual format, note it (e.g. 'dates are MM/DD/YYYY') and try again."
        )
    return rows
