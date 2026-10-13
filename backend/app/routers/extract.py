"""Receipt extraction endpoint (T4) + confidence gate & categorization (T5)."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..services import categorization, extraction, validation, vat
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

    # Guardrails run in code, independent of the model's self-reported confidence.
    check = validation.validate_receipt(
        result, confidence_threshold=settings.confidence_threshold
    )

    # Unreadable -> don't create a junk ledger row; ask for a clearer photo.
    if not check["readable"]:
        return {
            "expense": None,
            "extraction": result.model_dump(mode="json"),
            "gated_to": None,
            "readable": False,
            "issues": check["issues"],
        }

    # Store the image (best-effort; extraction still works if storage is down).
    image_url = None
    try:
        ext = (file.filename or "receipt.jpg").split(".")[-1]
        image_url = repo.upload_receipt(
            user_id, f"{uuid.uuid4()}.{ext}", content, file.content_type or "image/jpeg"
        )
    except Exception:  # noqa: BLE001 - storage optional for the demo
        image_url = None

    # Per-line VAT: each itemized line carries its own rate, so a mixed-rate
    # receipt is summed PER RATE in code rather than flattened to one rate.
    line_rows = [
        {
            "description": li.description,
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "amount": li.amount,
            "vat_rate": li.vat_rate,
            "vat_amount": vat.line_vat(li.amount, li.vat_rate) if li.amount is not None else None,
            "position": idx,
        }
        for idx, li in enumerate(result.line_items)
    ]
    breakdown = vat.vat_breakdown([r for r in line_rows if r["amount"] is not None])

    # When the lines carry real rates, the code-summed figures are the source of
    # truth for the expense's VAT (dominant rate kept for the single-rate display).
    if breakdown["rate_count"] > 0:
        dominant = max(
            (r for r in breakdown["rates"] if r["rate"] > 0), key=lambda r: r["gross"]
        )
        vat_info = {"vat_amount": breakdown["vat_amount"], "vat_rate": dominant["rate"]}
    else:
        vat_info = vat.resolve_vat(result.total or 0.0, result.vat_rate, result.vat_amount)

    valid = {c["name"] for c in repo.list_categories(user_id)}
    category = categorization.categorize(result.vendor, None, valid_categories=valid or None)

    # Duplicate check at UPLOAD time: if an identical purchase (same vendor + amount
    # + date) is already on the ledger, never auto-post — route to review so the user
    # double-checks before it lands. Consistent with the human-confirm-gate rule.
    dup_date = (result.date or date.today()).isoformat()
    duplicates = repo.find_duplicates(user_id, result.vendor, result.total, dup_date)
    if duplicates:
        d = duplicates[0]
        check["issues"].insert(
            0,
            f"Possible duplicate — {result.vendor} for €{float(result.total or 0):.2f} on "
            f"{dup_date} is already in your ledger. Check before posting.",
        )
        check["auto_post"] = False

    # Gate decided in code: auto-post only if confident AND no validation issues.
    status = "posted" if check["auto_post"] else "pending_review"

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
        # Surface the reasons on the review-queue card.
        "note": "; ".join(check["issues"]) or None,
        "confidence": round(result.confidence, 3),
        "status": status,
        "reconciled": False,
        "receipt_image_url": image_url,
        "raw_extraction": result.model_dump(mode="json"),
    }
    created = repo.insert_expense(user_id, row)

    # Persist the itemized lines (best-effort — the expense is already saved).
    line_items: list = []
    if line_rows:
        try:
            line_items = repo.insert_line_items(user_id, created["id"], line_rows)
        except Exception:  # noqa: BLE001 - line items are additive, never fatal
            line_items = []

    return {
        "expense": created,
        "extraction": result.model_dump(mode="json"),
        "line_items": line_items,
        "vat_breakdown": breakdown,
        "gated_to": status,
        "readable": True,
        "issues": check["issues"],
        "duplicate_of": [
            {
                "id": d["id"],
                "vendor": d.get("vendor"),
                "amount": d.get("amount"),
                "expense_date": d.get("expense_date"),
            }
            for d in duplicates
        ],
    }
