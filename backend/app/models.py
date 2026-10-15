"""Pydantic request/response models."""
from __future__ import annotations

import datetime
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


# --- Manual / cash expense entry (T3) --------------------------------------
class LineItemInput(BaseModel):
    """A single VAT line the user enters/edits (per-line VAT). `amount` is the
    gross (VAT-inclusive) line total; VAT is computed in code from amount + rate."""
    description: str | None = None
    amount: float = Field(gt=0)
    vat_rate: float | None = None
    quantity: float | None = None
    unit_price: float | None = None


class ExpenseStatusUpdate(BaseModel):
    """Change an expense's ledger status from the Ledger (e.g. send a posted row
    back to review). Reconciliation is a separate flag and isn't touched here."""
    status: Literal["pending_review", "confirmed", "posted"]


class ExpenseCategoryUpdate(BaseModel):
    """Re-categorize an expense directly from the Ledger category column."""
    category: str = Field(min_length=1)


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
    # Optional multi-rate breakdown: when present, VAT is summed PER RATE in code
    # from these lines (a mixed-rate receipt), overriding the single vat_rate above.
    line_items: list[LineItemInput] | None = None


# --- Extraction (T4/T5) -----------------------------------------------------
class LineItem(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None
    vat_rate: float | None = None          # per-line VAT rate (%), e.g. 23


class TaxLine(BaseModel):
    """One row of the receipt's PRINTED VAT/IVA summary table (the legal tax
    breakdown near the total: one row per rate with net / VAT / gross). These are
    TRANSCRIBED, never computed — they are the authoritative VAT figures, so we
    trust them over VAT re-derived from the model's reading of the item lines."""
    rate: float | None = None              # the printed % (e.g. 6, 13, 23)
    net: float | None = None               # "Total Liq." — base, VAT-exclusive
    vat: float | None = None               # "IVA" — the printed VAT for this rate
    gross: float | None = None             # "Total" — VAT-inclusive for this rate


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
    # The receipt's printed VAT summary table, transcribed. Authoritative VAT.
    tax_lines: list[TaxLine] = Field(default_factory=list)
    # Total discount applied (Special Offer / Desconto / Poupança), as a POSITIVE
    # magnitude. `total` is always the amount PAID after this discount, so the item
    # lines may sum above `total` by roughly this much.
    discount_total: float | None = None
    # True when the per-line vat_rate was ESTIMATED from the product type because the
    # receipt prints no VAT (e.g. Uber Eats). Such a receipt goes to review to confirm.
    vat_estimated: bool = False
    # The LLM's SUGGESTED category (it already read the receipt). Advisory only:
    # code applies rules first and validates this against the real category list.
    category: str | None = None
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


# --- Phase 2: subscriptions (Refund Hunter) --------------------------------
class SubscriptionUpdate(BaseModel):
    """User-owned fields on a detected subscription. (Realized savings are
    recorded on a refund_action in T15, not here.)"""
    status: Literal["active", "flagged", "cancelled"] | None = None
    usage_note: str | None = None


class RefundDraftRequest(BaseModel):
    action: Literal["cancel", "refund"] = "cancel"
    recipient: str | None = None           # where the user intends to send it


class RefundActionUpdate(BaseModel):
    """Approve/edit a draft. Nothing is ever auto-sent; 'done' = user handled it."""
    subject: str | None = None
    email_draft: str | None = None
    recipient: str | None = None
    status: Literal["draft", "sent", "done"] | None = None
    saved_amount: float | None = None


# --- Generic responses ------------------------------------------------------
class Message(BaseModel):
    message: str
    detail: Any | None = None
