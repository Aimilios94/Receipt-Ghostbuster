"""Bank statement import (T6) — CSV, or a PDF fallback when the user can't export CSV."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import get_current_user_id
from ..config import get_settings
from ..models import ColumnMapping
from ..services import csv_import, pdf_import, statements
from ..services.csv_import import CsvImportError
from ..services.pdf_import import PdfImportError
from .. import repository as repo

router = APIRouter(prefix="/bank", tags=["bank"])


def _is_pdf(filename: str | None, raw: bytes) -> bool:
    return (filename or "").lower().endswith(".pdf") or raw[:5] == b"%PDF-"


@router.post("/import")
async def import_statement(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    note: str | None = Form(None),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Upload a bank statement. A **CSV** (with an optional `mapping` JSON matching
    ColumnMapping) or a text-based **PDF** (parsed via pdf_import). `note` is an
    optional free-text hint passed to the PDF extractor (e.g. an unusual date format
    or which column is the amount). Both formats produce the same normalized rows."""
    raw = await file.read()

    try:
        if _is_pdf(file.filename, raw):
            rows = pdf_import.parse_bank_pdf(raw, get_settings(), note=note)
            source = "pdf"
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            col_map = ColumnMapping(**json.loads(mapping)) if mapping else ColumnMapping()
            rows = csv_import.parse_bank_csv(text, col_map)
            source = "csv"
    except (CsvImportError, PdfImportError) as exc:
        # A user-fixable problem (wrong columns, scanned PDF, bad date format).
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not rows:
        detail = (
            "No transactions found in the PDF. If it's a scanned image, export a CSV instead."
            if source == "pdf"
            else "No transactions parsed. Check the CSV has date and amount columns."
        )
        raise HTTPException(status_code=400, detail=detail)

    # One statement row per imported file: period + money in/out/net. Transactions
    # are linked to it so the UI can show a single entry per upload.
    stats = statements.statement_stats(rows)
    try:
        statement = repo.insert_bank_statement(
            user_id,
            {"filename": file.filename, "source_type": source, **stats},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Saving the statement failed: {str(exc)[:300]}"
        ) from exc

    for r in rows:
        r["source_file"] = file.filename
        r["raw"] = r.get("raw")
        r["statement_id"] = statement.get("id")

    try:
        inserted = repo.insert_bank_transactions(user_id, rows)
    except Exception as exc:  # noqa: BLE001 - surface a real message (with CORS headers)
        # Roll back the orphaned statement so a failed import leaves nothing behind.
        if statement.get("id"):
            try:
                repo.delete_bank_statement(user_id, statement["id"])
            except Exception:  # noqa: BLE001
                pass
        raise HTTPException(
            status_code=502,
            detail=f"Saving the transactions failed: {str(exc)[:300]}",
        ) from exc

    return {
        "imported": len(inserted),
        "transactions": inserted,
        "source": source,
        "statement": statement,
    }


@router.get("/statements")
def list_statements(user_id: str = Depends(get_current_user_id)) -> dict:
    """Every imported statement, newest first, each with a live `needs_receipt`
    count (purchases on it with no matched expense yet)."""
    stmts = repo.list_bank_statements(user_id)
    txns = repo.list_bank_transactions(user_id)
    by_stmt: dict[str, int] = {}
    for t in txns:
        if statements.needs_receipt(t) and t.get("statement_id"):
            by_stmt[t["statement_id"]] = by_stmt.get(t["statement_id"], 0) + 1
    for s in stmts:
        s["needs_receipt_count"] = by_stmt.get(s["id"], 0)
    return {"statements": stmts}


@router.get("/statements/{statement_id}/transactions")
def statement_transactions(
    statement_id: str, user_id: str = Depends(get_current_user_id)
) -> dict:
    statement = repo.get_bank_statement(user_id, statement_id)
    if not statement:
        raise HTTPException(status_code=404, detail="Statement not found.")
    txns = repo.list_statement_transactions(user_id, statement_id)
    return {
        "statement": statement,
        "transactions": [statements.annotate_transaction(t) for t in txns],
    }


@router.delete("/statements/{statement_id}")
def delete_statement(
    statement_id: str, user_id: str = Depends(get_current_user_id)
) -> dict:
    if not repo.get_bank_statement(user_id, statement_id):
        raise HTTPException(status_code=404, detail="Statement not found.")
    repo.delete_bank_statement(user_id, statement_id)
    return {"deleted": statement_id}
