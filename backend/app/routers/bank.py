"""Bank CSV import (T6)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import get_current_user_id
from ..models import ColumnMapping
from ..services import csv_import
from .. import repository as repo

router = APIRouter(prefix="/bank", tags=["bank"])


@router.post("/import")
async def import_csv(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Upload a bank-statement CSV. `mapping` is an optional JSON object matching
    ColumnMapping (column names + optional date_format / debit+credit columns)."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    col_map = ColumnMapping(**json.loads(mapping)) if mapping else ColumnMapping()

    rows = csv_import.parse_bank_csv(text, col_map)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="No transactions parsed. Check the column mapping matches the CSV headers.",
        )

    for r in rows:
        r["source_file"] = file.filename
        r["raw"] = r.get("raw")

    inserted = repo.insert_bank_transactions(user_id, rows)
    return {"imported": len(inserted), "transactions": inserted}
