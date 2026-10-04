"""Receipt extraction endpoint (T4) + confidence gate & categorization (T5)."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..services import categorization, extraction, vat
from .. import repository as repo

router = APIRouter(tags=["extraction"])


@router.post("/extract")
async def extract(
    file: UploadFile = File(...),
    source: str = Form("card"),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Upload a receipt image -> store it -> vision-LLM extract -> create an
    expense. Confidence gate decides posted vs pending_review. The LLM only reads;
    VAT is computed in code and status is decided in code."""
    if not settings.llm_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                f"LLM provider '{settings.llm_provider}' is not configured. Set the "
                "API key in backend/.env, or set LLM_PROVIDER=mock to test the pipeline."
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    result = extraction.extract_receipt(content, file.filename, settings)

    # Store the image (best-effort; extraction still works if storage is down).
    image_url = None
    try:
        ext = (file.filename or "receipt.jpg").split(".")[-1]
        image_url = repo.upload_receipt(
            user_id, f"{uuid.uuid4()}.{ext}", content, file.content_type or "image/jpeg"
        )
    except Exception:  # noqa: BLE001 - storage optional for the demo
        image_url = None

    # VAT computed in code from what the LLM read.
    vat_info = vat.resolve_vat(result.total or 0.0, result.vat_rate, result.vat_amount)

    valid = {c["name"] for c in repo.list_categories(user_id)}
    category = categorization.categorize(result.vendor, None, valid_categories=valid or None)

    # Confidence gate — decided in code, not by the model.
    status = "posted" if result.confidence >= settings.confidence_threshold else "pending_review"

    row = {
        "source": source if source in ("card", "cash", "bank") else "card",
        "input_method": "receipt",
        "vendor": result.vendor,
        "amount": result.total or 0.0,
        "currency": result.currency or settings.default_currency,
        "expense_date": (result.date or date.today()).isoformat(),
        "category": category,
        "vat_amount": vat_info["vat_amount"],
        "vat_rate": vat_info["vat_rate"],
        "confidence": round(result.confidence, 3),
        "status": status,
        "reconciled": False,
        "receipt_image_url": image_url,
        "raw_extraction": result.model_dump(mode="json"),
    }
    created = repo.insert_expense(user_id, row)
    return {
        "expense": created,
        "extraction": result.model_dump(mode="json"),
        "gated_to": status,
    }
