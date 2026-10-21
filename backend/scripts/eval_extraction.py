"""Extraction-accuracy eval harness.

Runs the REAL extraction pipeline (`extraction.extract_receipt` +
`receipt_fields.compute` — the same code the /extract endpoint uses, minus the
DB) over a labelled set of receipt photos and scores each field against hand-
verified ground truth. Produces:

  * a per-receipt breakdown (console, + a git-ignored detailed JSON), and
  * an aggregate field-level accuracy table written to backend/eval/RESULTS.md
    (aggregates only — no personal data — safe to commit and quote in the README).

Why score `receipt_fields.compute(...)` and not just the raw LLM JSON: the shipped
accuracy the user actually gets is the model read PLUS the deterministic VAT /
amount-paid / category logic (printed-table source of truth, discount scaling,
dominant-rate selection). That is the honest, user-facing number.

Usage (from the backend/ dir, with ANTHROPIC_API_KEY in backend/.env):
    python scripts/eval_extraction.py                 # all labelled receipts (cached)
    python scripts/eval_extraction.py --refresh       # ignore cache, re-call the LLM
    python scripts/eval_extraction.py --provider mock # smoke-test the harness, no key
    python scripts/eval_extraction.py --limit 3       # first 3 only

Extraction is cached per image under backend/eval/.cache/ so you can iterate on the
scorer without re-spending API calls; --refresh forces a fresh read.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any

# Windows consoles default to cp1252 and choke on the em-dash we print for empty
# fields; force UTF-8 so the report renders everywhere.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
EVAL_DIR = BACKEND / "eval"
RECEIPTS_DIR = EVAL_DIR / "receipts"
CACHE_DIR = EVAL_DIR / ".cache"
LABELS = EVAL_DIR / "labels.json"
RESULTS_MD = EVAL_DIR / "RESULTS.md"
DETAIL_JSON = EVAL_DIR / "results.detail.json"
METRICS_JSON = EVAL_DIR / "metrics.json"   # aggregates only — committable, served by the API

# Import the app the same way uvicorn would.
sys.path.insert(0, str(BACKEND))
from app.config import Settings  # noqa: E402
from app.models import ExtractionResult  # noqa: E402
from app.services import eval_metrics, extraction, gating, receipt_fields, validation  # noqa: E402

# Map the gate's status to the eval's gate vocabulary.
_GATE_MAP = {"posted": "auto_post", "pending_review": "review", "rejected": "reject"}

# The category list the extraction prompt offers (kept in sync with extraction.py /
# receipt_fields). Lets the harness validate the LLM's category suggestion offline,
# exactly as repo.list_categories would online.
CATEGORIES: set[str] = {
    "Groceries", "Dining & Cafes", "Transport & Fuel", "Utilities",
    "Rent & Housing", "Software & Subscriptions", "Office & Supplies", "Travel",
    "Health & Pharmacy", "Entertainment", "Professional Services",
    "Taxes & Fees", "Tobacco", "Income",
}

# Fields we can score, in display order. Money fields use a cents tolerance; the
# rest are exact (vendor is fuzzy; see _vendor_match).
MONEY_TOL = 0.01
VAT_TOL = 0.02


# --------------------------------------------------------------------------- #
# Scoring helpers
# --------------------------------------------------------------------------- #
def _norm(s: Any) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s or "").lower())).strip()


def _vendor_match(expected: str, alts: list[str], predicted: Any) -> bool:
    """Fuzzy vendor match: a hit if any accepted name is a substring of the
    prediction (either direction) or shares a significant (>=4 char) token.
    `alts` lets a legitimately ambiguous receipt accept more than one answer
    (e.g. the payment processor OR the merchant)."""
    pn = _norm(predicted)
    if not pn:
        return False
    for cand in [expected, *alts]:
        cn = _norm(cand)
        if not cn:
            continue
        if cn in pn or pn in cn:
            return True
        ptoks = set(pn.split())
        if any(t in ptoks for t in cn.split() if len(t) >= 4):
            return True
    return False


def _money_match(expected: float, predicted: Any, tol: float) -> bool:
    try:
        return predicted is not None and abs(float(expected) - float(predicted)) <= tol
    except (TypeError, ValueError):
        return False


def _rate_match(expected: Any, predicted: Any) -> bool:
    try:
        return predicted is not None and round(float(expected)) == round(float(predicted))
    except (TypeError, ValueError):
        return False


def _exact_match(expected: Any, predicted: Any) -> bool:
    return _norm(expected) == _norm(predicted) and _norm(expected) != ""


def _score_fields(label: dict[str, Any], pred: dict[str, Any]) -> dict[str, bool]:
    """Compare only the fields the label actually specifies — partial labels are
    fine, so a receipt with no printed VAT simply isn't scored on VAT."""
    out: dict[str, bool] = {}
    if "vendor" in label:
        out["vendor"] = _vendor_match(label["vendor"], label.get("vendor_alt", []), pred["vendor"])
    if "date" in label:
        out["date"] = label["date"] == pred["date"]
    if "total" in label:
        out["total"] = _money_match(label["total"], pred["total"], MONEY_TOL)
    if "vat_amount" in label:
        out["vat_amount"] = _money_match(label["vat_amount"], pred["vat_amount"], VAT_TOL)
    if "vat_rate" in label:
        out["vat_rate"] = _rate_match(label["vat_rate"], pred["vat_rate"])
    if "category" in label:
        out["category"] = _exact_match(label["category"], pred["category"])
    return out


# --------------------------------------------------------------------------- #
# Extraction (with a per-image cache so scorer iteration is free)
# --------------------------------------------------------------------------- #
def _extract(path: Path, settings: Settings, today: datetime.date, *, use_cache: bool) -> ExtractionResult:
    """Return the ExtractionResult for one image, mirroring the /extract date
    re-read + year-repair steps. Cached as JSON unless --refresh."""
    model = settings.anthropic_model if settings.llm_provider == "anthropic" else settings.openai_model
    model_tag = re.sub(r"[^a-z0-9]+", "-", model.lower())
    cache = CACHE_DIR / f"{path.stem}.{settings.llm_provider}.{model_tag}.json"
    if use_cache and cache.exists():
        return ExtractionResult.model_validate_json(cache.read_text(encoding="utf-8"))

    image_bytes = path.read_bytes()
    result, oriented, _trace = extraction.extract_receipt(image_bytes, path.name, settings)

    # Mirror the router: re-read a suspicious date, then deterministically repair a
    # misread year. On a recent, clean set these are no-ops, but we keep them so the
    # number reflects the shipped pipeline, not a stripped-down one.
    d = result.date
    if d is None or d > today or (today - d).days > validation.MAX_AGE_DAYS:
        better = extraction.reread_date(oriented, path.name, settings, today)
        if better is not None and better != result.date:
            result.date = better
    if result.date is not None:
        fixed = validation.repair_year(result.date, today)
        if fixed is not None:
            result.date = fixed

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(result.model_dump_json(), encoding="utf-8")
    return result


def _predict(result: ExtractionResult, fields: dict[str, Any]) -> dict[str, Any]:
    """Turn a raw read into the user-facing fields the app would store."""
    return {
        "vendor": result.vendor,
        "date": result.date.isoformat() if result.date else None,
        "total": fields["amount"],
        "currency": result.currency,
        "vat_amount": fields["vat_amount"],
        "vat_rate": fields["vat_rate"],
        "category": fields["category"],
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
# Currency is intentionally NOT scored: these receipts print a € symbol, not the
# ISO text "EUR", so the model reads null and the app correctly defaults to EUR.
# Grading it would be either unfair (0%) or a padded gimme (100%).
FIELDS = ["vendor", "date", "total", "vat_amount", "vat_rate", "category"]


def _fmt(v: Any) -> str:
    return "—" if v is None else str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description="Receipt extraction-accuracy eval.")
    ap.add_argument("--labels", default=str(LABELS), help="path to labels.json")
    ap.add_argument("--receipts", default=str(RECEIPTS_DIR), help="dir of receipt images (default eval/receipts)")
    ap.add_argument("--provider", default=None, help="override LLM_PROVIDER (anthropic|openai|mock)")
    ap.add_argument("--model", default=None, help="override the model (e.g. gpt-5-mini); also keys the cache")
    ap.add_argument("--limit", type=int, default=None, help="only the first N receipts")
    ap.add_argument("--refresh", action="store_true", help="ignore cache, re-call the LLM")
    args = ap.parse_args()

    labels_path = Path(args.labels)
    if not labels_path.exists():
        print(f"No labels file at {labels_path}. See backend/eval/README.md for the format.")
        return 2
    labels: list[dict[str, Any]] = json.loads(labels_path.read_text(encoding="utf-8"))
    if args.limit:
        labels = labels[: args.limit]
    receipts_dir = Path(args.receipts)

    settings = Settings(_env_file=str(BACKEND / ".env"))
    if args.provider:
        settings.llm_provider = args.provider
    if args.model:
        if (args.provider or settings.llm_provider) == "anthropic":
            settings.anthropic_model = args.model
        else:
            settings.openai_model = args.model
    if not settings.llm_configured:
        print(f"LLM provider '{settings.llm_provider}' is not configured (no key). "
              "Set it in backend/.env, or run --provider mock.")
        return 2

    today = datetime.date.today()
    print(f"Provider: {settings.llm_provider} | model: "
          f"{settings.anthropic_model if settings.llm_provider == 'anthropic' else settings.openai_model}")
    print(f"Receipts: {len(labels)} | cache: {'off (refresh)' if args.refresh else 'on'}\n")

    # tally[field] = [correct, scored]
    tally: dict[str, list[int]] = {f: [0, 0] for f in FIELDS}
    receipts_fully_correct = 0
    details: list[dict[str, Any]] = []
    gate_rows: list[dict[str, Any]] = []   # one per read, for the guardrail metrics
    slice_rows: list[dict[str, Any]] = []  # one per read, for accuracy-by-receipt-type

    for label in labels:
        name = label["file"]
        path = receipts_dir / name
        row: dict[str, Any] = {"file": name}
        if not path.exists():
            print(f"  MISSING  {name} — not in {receipts_dir}")
            details.append({**row, "error": "image missing"})
            continue
        try:
            result = _extract(path, settings, today, use_cache=not args.refresh)
            fields = receipt_fields.compute(result, CATEGORIES)
            pred = _predict(result, fields)
        except Exception as exc:  # noqa: BLE001 - a failed read scores as all-miss
            print(f"  ERROR    {name}: {exc}")
            traceback.print_exc()
            scored = _score_fields(label, {f: None for f in FIELDS})
            for f, ok in scored.items():
                tally[f][1] += 1
            details.append({**row, "error": str(exc)})
            continue

        scored = _score_fields(label, pred)
        for f, ok in scored.items():
            tally[f][0] += int(ok)
            tally[f][1] += 1
        all_ok = all(scored.values())
        receipts_fully_correct += int(all_ok)
        slice_rows.append({"tags": label.get("tags", []), "scored": scored})

        # Run the SHIPPED gate (gating.decide_gate — the same function /extract uses)
        # and record it against whether the read was actually correct, so we can
        # measure the guardrails (did a wrong read get caught?). expected_gate is an
        # OPTIONAL hand label; the core metrics don't need it. Year-repair isn't
        # separately exercised here (the set is recent, so it's a no-op).
        check = validation.validate_receipt(result, confidence_threshold=settings.confidence_threshold)
        gate = gating.decide_gate(result, check, fields, settings, today)
        gate_rows.append({
            "file": name,
            "expected_gate": label.get("expected_gate"),
            "predicted_gate": _GATE_MAP.get(gate["gated_to"]),
            "field_correct": all_ok if scored else None,
            "confidence": result.confidence,
            "guardrails_fired": gate["guardrails_fired"],
        })

        mark = "OK  " if all_ok else "MISS"
        misses = [f for f, ok in scored.items() if not ok]
        print(f"  {mark}  {name:<22} " + ("" if all_ok else "wrong: " + ", ".join(misses)))
        for f in misses:
            print(f"            {f}: expected {_fmt(label.get(f))!r}  got {_fmt(pred.get(f))!r}")

        details.append({
            "file": name,
            "all_correct": all_ok,
            "scored": scored,
            "expected": {f: label[f] for f in FIELDS if f in label},
            "predicted": {f: pred[f] for f in FIELDS},
        })

    # ---- aggregate ----
    def pct(c: int, n: int) -> str:
        return f"{100.0 * c / n:5.1f}%" if n else "   n/a"

    total_correct = sum(t[0] for t in tally.values())
    total_scored = sum(t[1] for t in tally.values())
    n = len([d for d in details if "error" not in d])

    print("\n" + "=" * 52)
    print("Field-level accuracy")
    print("-" * 52)
    print(f"{'field':<14}{'accuracy':>10}{'correct/scored':>18}")
    for f in FIELDS:
        c, t = tally[f]
        print(f"{f:<14}{pct(c, t):>10}{f'{c}/{t}':>18}")
    print("-" * 52)
    print(f"{'OVERALL':<14}{pct(total_correct, total_scored):>10}{f'{total_correct}/{total_scored}':>18}")
    print(f"{'receipts 100%':<14}{pct(receipts_fully_correct, n):>10}{f'{receipts_fully_correct}/{n}':>18}")
    print("=" * 52)

    # Guardrail effectiveness: did the gate catch the reads that were actually wrong?
    routing = eval_metrics.routing_scores(gate_rows)
    calibration = eval_metrics.confidence_calibration(gate_rows)
    confusion = eval_metrics.confusion_matrix(gate_rows) if routing["n_labelled"] else None
    slices = eval_metrics.slice_accuracy(slice_rows)

    def rpct(v: Any) -> str:
        return "n/a" if v is None else f"{100.0 * v:.0f}%"

    print("\nGuardrail effectiveness")
    print("-" * 52)
    print(f"  wrong reads caught by the gate : {rpct(routing['guardrail_recall_on_wrong'])} "
          f"({routing['wrong_reads'] - routing['false_auto_posts']}/{routing['wrong_reads']})")
    print(f"  false auto-posts (wrong & posted): {routing['false_auto_posts']} "
          f"({rpct(routing['false_auto_post_rate'])} of wrong reads)")
    print(f"  over-review (correct, held back) : {rpct(routing['over_review_rate'])} "
          f"({routing['over_reviewed']}/{routing['correct_reads']})")
    print("\nConfidence calibration (accuracy by self-reported confidence)")
    print("-" * 52)
    for b in calibration:
        if b["n"]:
            print(f"  {b['range']:>9} : {rpct(b['accuracy']):>5}  (n={b['n']})")
    print("=" * 52)

    if slices:
        print("\nAccuracy by receipt type")
        print("-" * 52)
        for tag, s in slices.items():
            print(f"  {tag:<16} : {rpct(s['accuracy']):>5}  "
                  f"({s['correct']}/{s['scored']} fields, {s['n_receipts']} receipts)")
        print("=" * 52)

    # A run where nothing read successfully (e.g. the provider is out of credits or
    # unreachable) must NOT clobber a good RESULTS.md with zeros.
    if n == 0:
        print("\nNo receipts read successfully — leaving RESULTS.md untouched. "
              "Check the provider/API errors above.")
        return 1

    _write_results_md(settings, tally, total_correct, total_scored, receipts_fully_correct,
                      n, today, routing, calibration, slices)
    _write_metrics_json(settings, tally, total_correct, total_scored, receipts_fully_correct,
                        n, today, routing, calibration, confusion, slices)
    DETAIL_JSON.write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {RESULTS_MD.relative_to(BACKEND.parent)} + {METRICS_JSON.name} (aggregates, "
          f"committable) and {DETAIL_JSON.name} (per-receipt, git-ignored).")
    return 0


def _write_results_md(settings, tally, total_correct, total_scored,
                      fully_correct, n, today, routing, calibration, slices) -> None:
    def pct(c, t):
        return f"{100.0 * c / t:.1f}%" if t else "n/a"

    def rpct(v):
        return "n/a" if v is None else f"{100.0 * v:.0f}%"

    model = settings.anthropic_model if settings.llm_provider == "anthropic" else settings.openai_model
    lines = [
        "# Extraction accuracy",
        "",
        f"Field-level accuracy of the receipt-extraction pipeline over a hand-labelled "
        f"set of **{n}** real Portuguese receipts (multi-rate VAT, rotated photos, "
        f"discounts, and a payment-only receipt). Generated by "
        f"`backend/scripts/eval_extraction.py`.",
        "",
        f"- **Provider / model:** {settings.llm_provider} · `{model}`",
        f"- **Run date:** {today.isoformat()}",
        f"- **Scored:** the user-facing fields after the deterministic VAT / amount / "
        f"category logic (not just the raw LLM JSON).",
        "",
        "| Field | Accuracy | Correct / scored |",
        "|---|---:|---:|",
    ]
    for f in FIELDS:
        c, t = tally[f]
        lines.append(f"| {f} | {pct(c, t)} | {c}/{t} |")
    lines += [
        f"| **Overall** | **{pct(total_correct, total_scored)}** | {total_correct}/{total_scored} |",
        f"| Receipts fully correct | {pct(fully_correct, n)} | {fully_correct}/{n} |",
        "",
        "> Notes: `total` is the amount paid after discounts; `vat_amount`/`vat_rate` "
        "are scored only on receipts that print a VAT table (dominant rate for the "
        "single-rate column); vendor matching is fuzzy (merchant or payment processor).",
        "",
        "## Guardrail effectiveness",
        "",
        "Does the review gate actually catch the reads that are wrong? Measured by "
        "running the shipped gate (`services/gating.decide_gate`) over the same set and "
        "comparing its decision against whether each read was actually correct.",
        "",
        "| Metric | Value | |",
        "|---|---:|---|",
        f"| Wrong reads caught by the gate | **{rpct(routing['guardrail_recall_on_wrong'])}** | "
        f"{routing['wrong_reads'] - routing['false_auto_posts']}/{routing['wrong_reads']} wrong reads routed to review |",
        f"| False auto-posts | **{routing['false_auto_posts']}** | a wrong read that still auto-posted "
        f"({rpct(routing['false_auto_post_rate'])} of wrong reads) |",
        f"| Over-review | {rpct(routing['over_review_rate'])} | correct reads sent to review anyway "
        f"({routing['over_reviewed']}/{routing['correct_reads']}) — friction, not risk |",
        "",
        "## Confidence calibration",
        "",
        "Accuracy grouped by the model's self-reported confidence — does higher "
        "confidence actually mean a more accurate read?",
        "",
        "| Confidence | Accuracy | Reads |",
        "|---|---:|---:|",
    ]
    for b in calibration:
        if b["n"]:
            lines.append(f"| {b['range']} | {rpct(b['accuracy'])} | {b['n']} |")
    if slices:
        lines += [
            "",
            "## Accuracy by receipt type",
            "",
            "Field-level accuracy split by receipt characteristic (a receipt counts "
            "toward every tag it carries), so a strong average can't hide a weak slice.",
            "",
            "| Receipt type | Accuracy | Correct / scored | Receipts |",
            "|---|---:|---:|---:|",
        ]
        for tag, s in slices.items():
            lines.append(f"| {tag} | {pct(s['correct'], s['scored'])} | "
                         f"{s['correct']}/{s['scored']} | {s['n_receipts']} |")
    lines.append("")
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def _write_metrics_json(settings, tally, total_correct, total_scored,
                        fully_correct, n, today, routing, calibration, confusion, slices) -> None:
    """Aggregate metrics for the API/dashboard. Aggregates only — no receipt data —
    so it is safe to commit."""
    model = settings.anthropic_model if settings.llm_provider == "anthropic" else settings.openai_model
    data = {
        "provider": settings.llm_provider,
        "model": model,
        "run_date": today.isoformat(),
        "n_receipts": n,
        "fields": {
            f: {"accuracy": (tally[f][0] / tally[f][1]) if tally[f][1] else None,
                "correct": tally[f][0], "scored": tally[f][1]}
            for f in FIELDS
        },
        "overall": {
            "accuracy": (total_correct / total_scored) if total_scored else None,
            "correct": total_correct, "scored": total_scored,
        },
        "receipts_fully_correct": {"count": fully_correct, "n": n},
        "guardrails": routing,
        "calibration": calibration,
        "confusion": confusion,
        "slices": slices,
    }
    METRICS_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
