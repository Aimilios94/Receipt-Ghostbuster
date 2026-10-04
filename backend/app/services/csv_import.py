"""Parse an uploaded bank-statement CSV into normalized transaction dicts.

Configurable column mapping (see models.ColumnMapping). Handles either a single
signed `amount` column or separate debit/credit columns. Amounts are normalized
to SIGNED values (negative = money out). Pure function — no DB, no network.
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
)


def _parse_date(value: str, explicit_format: str | None) -> str:
    value = (value or "").strip()
    if explicit_format:
        return datetime.strptime(value, explicit_format).date().isoformat()
    for fmt in _COMMON_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    # Last resort: ISO-ish prefix.
    return value[:10]


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


def parse_bank_csv(content: str, mapping: ColumnMapping) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(content))
    rows: list[dict[str, Any]] = []

    for raw in reader:
        # Case-insensitive header lookup.
        lookup = { (k or "").strip().lower(): v for k, v in raw.items() }

        def col(name: str | None):
            if not name:
                return None
            return lookup.get(name.strip().lower())

        date_str = _parse_date(col(mapping.date) or "", mapping.date_format)

        if mapping.debit or mapping.credit:
            debit = _parse_money(col(mapping.debit)) or 0.0
            credit = _parse_money(col(mapping.credit)) or 0.0
            amount = credit - debit         # credit in (+), debit out (-)
        else:
            amount = _parse_money(col(mapping.amount))

        if amount is None:
            continue  # skip rows with no parseable amount (e.g. header repeats)

        rows.append(
            {
                "txn_date": date_str,
                "description": (col(mapping.description) or "").strip() or None,
                "amount": round(amount, 2),
                "balance": _parse_money(col(mapping.balance)),
                "raw": raw,
            }
        )

    return rows
