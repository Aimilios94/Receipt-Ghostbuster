"""Receipt extraction endpoint (T4) + confidence gate & categorization (T5)."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import get_current_user_id
from ..config import Settings, get_settings
from ..services import categorization, extraction, gating, receipt_fields, validation, vat
from .. import repository as repo

router = APIRouter(tags=["extraction"])


def _record_trace(user_id: str, trace: dict, **meta) -> None:
    """Persist an LLM-call trace, best-effort — observability must never break a read."""
    try:
        repo.insert_llm_trace(user_id, trace, meta)
    except Exception:  # noqa: BLE001
        pass


@router.post("/expenses/{expense_id}/rescan")
async def rescan_receipt(
    expense_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Replace an existing expense's receipt photo with a newly uploaded one and
    re-read it: the straightened new image is stored and, when it reads cleanly, the
    amount / VAT / vendor / date / category / line items are refreshed from it. If the
    new photo can't be read, the image is still replaced but the existing figures are
    kept (so a bad re-shot never wipes good data)."""
    if not settings.llm_configured:
        raise HTTPException(status_code=503, detail="LLM provider is not configured.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    result, oriented, trace = extraction.extract_receipt(content, file.filename, settings)

    # Store the straightened new image (best-effort).
    image_url = None
    try:
        image_url = repo.upload_receipt(user_id, f"{uuid.uuid4()}.jpg", oriented, "image/jpeg")
    except Exception:  # noqa: BLE001
        image_url = None

    check = validation.validate_receipt(result, confidence_threshold=settings.confidence_threshold)

    # Unreadable new photo: swap the image only, keep the existing figures.
    if not check["readable"]:
        _record_trace(user_id, trace, source="rescan", expense_id=expense_id,
                      gated_to="unreadable", readable=False, confidence=round(result.confidence, 3),
                      issues=check["issues"])
        patch = {"receipt_image_url": image_url} if image_url else {}
        updated = repo.update_expense(user_id, expense_id, patch) if patch else None
        return {
            "expense": updated,
            "readable": False,
            "issues": check["issues"],
            "message": "New photo saved, but it couldn't be read — kept the existing amounts.",
        }

    valid = {c["name"] for c in repo.list_categories(user_id)}
    fields = receipt_fields.compute(result, valid)

    row = {
        "input_method": "receipt",
        "vendor": result.vendor,
        "amount": fields["amount"] or 0.0,
        "currency": result.currency or settings.default_currency,
        "expense_date": (result.date or date.today()).isoformat(),
        "category": fields["category"],
        "vat_amount": fields["vat_amount"],
        "vat_rate": fields["vat_rate"],
        "confidence": round(result.confidence, 3),
        "raw_extraction": result.model_dump(mode="json"),
    }
    if image_url:
        row["receipt_image_url"] = image_url
    updated = repo.update_expense(user_id, expense_id, row)
    try:
        repo.replace_line_items(user_id, expense_id, fields["line_rows"])
    except Exception:  # noqa: BLE001 - line items are additive, never fatal
        pass

    _record_trace(user_id, trace, source="rescan", expense_id=expense_id,
                  gated_to="rescan", readable=True, confidence=round(result.confidence, 3))
    return {"expense": updated, "readable": True}


@router.post("/extract")
async def extract(
    file: UploadFile = File(...),
    source: str = Form("card"),
    note: str | None = Form(None),
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

    # Returns the read plus the auto-rotated (upright) image bytes we should store.
    # `note` is an optional hint the uploader typed in to help resolve ambiguity.
    result, oriented, trace = extraction.extract_receipt(content, file.filename, settings, note=note)

    # "Think twice" about a suspicious date: if the first read is missing, in the
    # future, or implausibly old (a misread year — the #1 extraction error on crumpled
    # receipts), re-read ONLY the date with a focused prompt and accept it only if the
    # second reading is plausible. This is an honest re-read, not a guess.
    today = date.today()
    d = result.date
    date_suspect = d is None or d > today or (today - d).days > validation.MAX_AGE_DAYS
    if date_suspect:
        better = extraction.reread_date(oriented, file.filename, settings, today)
        if better is not None and better != result.date:
            result.date = better

    # If the date is STILL implausibly old after re-reading, the year was almost
    # certainly misread (OCR reads a crumpled "2026" as "2023"). Snap the year to the
    # most recent plausible one deterministically and force review so the user confirms.
    year_repair: tuple[date, date] | None = None
    if result.date is not None:
        fixed = validation.repair_year(result.date, today)
        if fixed is not None:
            year_repair = (result.date, fixed)
            result.date = fixed

    # Guardrails run in code, independent of the model's self-reported confidence.
    # The full routing decision (readable/estimated-VAT/self-consistency/retake, plus
    # the year-repair and duplicate overrides) is made by gating.decide_gate below —
    # the SAME function the eval harness uses to measure the gate.
    check = validation.validate_receipt(
        result, confidence_threshold=settings.confidence_threshold
    )

    # Unreadable -> don't create a junk ledger row; ask for a clearer photo.
    if not check["readable"]:
        _record_trace(user_id, trace, source="extract", filename=file.filename,
                      gated_to="rejected", readable=False, confidence=round(result.confidence, 3),
                      issues=check["issues"])
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
        # Store the auto-rotated (upright) image so the saved receipt reads normally.
        image_url = repo.upload_receipt(
            user_id, f"{uuid.uuid4()}.jpg", oriented, "image/jpeg"
        )
    except Exception:  # noqa: BLE001 - storage optional for the demo
        image_url = None

    # VAT source of truth: the receipt's PRINTED IVA summary table, when the model
    # transcribed it and its gross-per-rate ties to the total. We trust those printed
    # figures over VAT re-derived from item amounts the model may have misread — so a
    # crumpled receipt's VAT still matches the printed tax summary to the cent. Each
    # printed rate becomes one gross bucket (also what seeds the review VAT editor).
    printed_buckets = vat.tax_line_buckets([tl.model_dump() for tl in result.tax_lines])
    printed_gross = round(sum(b["amount"] for b in printed_buckets), 2)
    # Relative tie tolerance + scale-to-total so a small OCR digit misread on a
    # crumpled receipt doesn't drop the authoritative printed table (see receipt_fields).
    _tol = max(0.10, 0.02 * (result.total or 0.0))
    use_printed = bool(printed_buckets) and (
        not result.total or abs(printed_gross - result.total) <= _tol
    )
    if use_printed and result.total and printed_gross and abs(printed_gross - result.total) > 0.01:
        _scale = result.total / printed_gross
        for b in printed_buckets:
            b["amount"] = round(b["amount"] * _scale, 2)
        _diff = round(result.total - sum(b["amount"] for b in printed_buckets), 2)
        if _diff:
            _big = max(printed_buckets, key=lambda b: b["amount"])
            _big["amount"] = round(_big["amount"] + _diff, 2)

    if use_printed:
        line_rows = [
            {
                "description": "Items",
                "quantity": None,
                "unit_price": None,
                "amount": b["amount"],
                "vat_rate": b["vat_rate"],
                "vat_amount": vat.line_vat(b["amount"], b["vat_rate"]),
                "position": idx,
            }
            for idx, b in enumerate(printed_buckets)
        ]
    else:
        # Fallback (no usable printed table): per-line VAT from the item rows, each
        # carrying its own rate, summed PER RATE in code rather than flattened.
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
        # Discounted receipt (e.g. Uber Eats "Special Offer"): the item lines are at
        # FULL price and sum above the amount paid. Scale them down proportionally so the
        # discount lands on each line and VAT is computed on what was ACTUALLY paid.
        items_sum = round(sum(r["amount"] for r in line_rows if r["amount"] is not None), 2)
        if result.discount_total and result.total and items_sum > result.total + 0.01:
            scale = result.total / items_sum
            for r in line_rows:
                if r["amount"] is not None:
                    r["amount"] = round(r["amount"] * scale, 2)
                    r["vat_amount"] = vat.line_vat(r["amount"], r["vat_rate"])
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

    # Amount paid = net + VAT. The model sometimes reads the receipt's NET/BASE line as
    # the "total" (e.g. Auchan's "BASE 3,77" vs the 4,18 actually paid). When the lines
    # give a coherent gross and the model's total matches their NET rather than their
    # GROSS, trust the gross (the real amount paid).
    amount_paid = result.total
    g, net = breakdown["gross"], breakdown["net"]
    if g and result.total and abs(result.total - net) <= 0.05 and abs(result.total - g) > 0.05:
        amount_paid = g
    elif not amount_paid:
        amount_paid = g or printed_gross or 0.0

    # Categorize: deterministic keyword rules first (fast, free, auditable); if the
    # vendor is unknown to the rules, fall back to the category the LLM suggested
    # while it was already reading the receipt. The suggestion is only accepted if it
    # matches a real category, so a bad guess degrades to "Uncategorized".
    valid = {c["name"] for c in repo.list_categories(user_id)}
    category = categorization.categorize(
        result.vendor,
        None,
        llm_fallback=lambda _: result.category,
        valid_categories=valid or None,
    )

    # Duplicate check at UPLOAD time: if the SAME purchase (same vendor + total,
    # within ~30 days) is already on the ledger, never auto-post — route to review
    # so the user double-checks before it lands. We match on vendor + exact total
    # (the strong fingerprint) with a date window, because the date is the most-
    # misread field (D16) — two photos of one receipt often disagree on it.
    # Consistent with the human-confirm-gate rule.
    dup_date = (result.date or date.today()).isoformat()
    duplicates = repo.find_duplicates(user_id, result.vendor, result.total, dup_date)
    dup_issue = None
    if duplicates:
        d = duplicates[0]
        existing_date = d.get("expense_date") or "an unknown date"
        same_day = existing_date == dup_date
        when = (
            f"on {existing_date}"
            if same_day
            else f"dated {existing_date} (this one reads {dup_date} — dates often misread)"
        )
        dup_issue = (
            f"Possible duplicate — {result.vendor} for €{float(result.total or 0):.2f} "
            f"is already in your ledger {when}. Compare the receipts before posting."
        )

    # The full gate decision (estimated-VAT, self-consistency, retake, plus the
    # year-repair and duplicate overrides) — the SAME pure function the eval uses.
    gate = gating.decide_gate(
        result,
        check,
        {"use_printed": use_printed, "breakdown": breakdown, "vat_amount": vat_info.get("vat_amount")},
        settings,
        today,
        year_repair=year_repair,
        duplicate_issue=dup_issue,
    )
    check["issues"] = gate["issues"]
    retake_suggested = gate["retake_suggested"]
    status = gate["gated_to"]

    row = {
        "source": source if source in ("card", "cash", "bank") else "card",
        "input_method": "receipt",
        "vendor": result.vendor,
        "amount": amount_paid or 0.0,
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

    _record_trace(user_id, trace, source="extract", filename=file.filename,
                  gated_to=status, readable=True, confidence=round(result.confidence, 3),
                  retake_suggested=retake_suggested, duplicate=bool(duplicates),
                  guardrails_fired=gate["guardrails_fired"],
                  issues=check["issues"], expense_id=created["id"])

    return {
        "expense": created,
        "extraction": result.model_dump(mode="json"),
        "line_items": line_items,
        "vat_breakdown": breakdown,
        "gated_to": status,
        "readable": True,
        "retake_suggested": retake_suggested,
        "issues": check["issues"],
        "duplicate_of": [
            {
                "id": d["id"],
                "vendor": d.get("vendor"),
                "amount": d.get("amount"),
                "vat_amount": d.get("vat_amount"),
                "expense_date": d.get("expense_date"),
                "category": d.get("category"),
                "receipt_image_url": d.get("receipt_image_url"),
            }
            for d in duplicates
        ],
    }
