"""Pydantic request/response models."""
from __future__ import annotations

import datetime
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


# --- Manual / cash expense entry (T3) --------------------------------------
class ExpenseCreate(BaseModel):
    amount: float = Field(gt=0)
    category: str | None = None
    note: str | None = None
    vendor: str | None = None
    source: Literal["cash", "card"] = "cash"
    expense_date: date | None = None       # defaults to today server-side
    currency: str | None = None            # defaults to DEFAULT_CURRENCY
    vat_rate: float | None = None          # optional; if given we compute vat_amount
    vat_amount: float | None = None        # optional explicit override


# --- Extraction (T4/T5) -----------------------------------------------------
class LineItem(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class ExtractionResult(BaseModel):
    """Structured output of the vision LLM. The LLM NEVER decides posting status
    or does reconciliation math — it only reports what it read, plus a confidence."""
    vendor: str | None = None
    # Fully-qualified on purpose: a field named `date` would otherwise shadow the
    # `date` type during Python 3.14's lazy annotation evaluation.
    date: datetime.date | None = None
    total: float | None = None
    vat_amount: float | None = None
    vat_rate: float | None = None
    currency: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    confidence: float = 0.0


# --- Bank CSV import (T6) ----------------------------------------------------
class ColumnMapping(BaseModel):
    """Maps CSV header names to our fields. All but date+amount are optional."""
    date: str = "date"
    amount: str = "amount"
    description: str | None = "description"
    balance: str | None = "balance"
    date_format: str | None = None         # strptime format; None = auto-detect
    # If the CSV uses separate debit/credit columns instead of a signed amount:
    debit: str | None = None
    credit: str | None = None


# --- Generic responses ------------------------------------------------------
class Message(BaseModel):
    message: str
    detail: Any | None = None
