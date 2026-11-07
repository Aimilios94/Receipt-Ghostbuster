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

Usage (from the backend/ dir, with the provider's API key in backend/.env):
    python scripts/eval_extraction.py                 # all labelled receipts (cached)
    python scripts/eval_extraction.py --refresh       # ignore cache, re-call the LLM
    python scripts/eval_extraction.py --provider mock # smoke-test the harness, no key
    python scripts/eval_extraction.py --limit 3       # first 3 only
    python scripts/eval_extraction.py --test-set      # the frozen held-out set, eval/test/

Extraction is cached per image under backend/eval/.cache/ so you can iterate on the
scorer without re-spending API calls; --refresh forces a fresh read.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
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
TEST_DIR = EVAL_DIR / "test"               # the held-out set, kept apart from the development set

# Import the app the same way uvicorn would.
sys.path.insert(0, str(BACKEND))
from app.config import Settings  # noqa: E402
from app.models import ExtractionResult  # noqa: E402
from app.services import eval_metrics, extraction, gating, receipt_fields, validation  # noqa: E402
from app.services.llm_trace import price_usd  # noqa: E402

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


def score_vat_lines(lines: list[dict[str, Any]], breakdown: dict[str, Any] | None) -> dict[str, Any]:
    """One receipt's VAT, rate by rate, against the figures the app would store. A rate is right
    when its net, VAT and total all match. An invented rate fails the receipt, not a line."""
    read = {round(float(r["rate"])): r for r in (breakdown or {}).get("rates", [])}
    correct = 0
    for line in lines:
        got = read.get(round(float(line["rate"])))
        if got and (_money_match(line["gross"], got["gross"], MONEY_TOL)
                    and _money_match(line["vat"], got["vat_amount"], VAT_TOL)
                    and _money_match(line["net"], got["net"], VAT_TOL)):
            correct += 1
    extra = sorted(set(read) - {round(float(line["rate"])) for line in lines})
    return {"correct": correct, "scored": len(lines), "extra_rates": extra,
            "all_correct": correct == len(lines) and not extra}


def new_vat_lines_tally() -> dict[str, int]:
    return {"correct": 0, "scored": 0, "receipts_correct": 0, "receipts": 0, "extra_rates": 0}


def add_vat_lines(tally: dict[str, int], label: dict[str, Any], breakdown: dict[str, Any] | None) -> dict[str, Any] | None:
    """Count one receipt towards the per-rate score. A failed read passes breakdown=None and scores
    as a miss. A label with no per-rate figures isn't scored here at all."""
    if not label.get("vat_lines"):
        return None
    score = score_vat_lines(label["vat_lines"], breakdown)
    tally["correct"] += score["correct"]
    tally["scored"] += score["scored"]
    tally["receipts_correct"] += int(score["all_correct"])
    tally["receipts"] += 1
    tally["extra_rates"] += len(score["extra_rates"])
    return score


def summarize_vat_lines(tally: dict[str, int]) -> dict[str, Any] | None:
    """The per-rate score for reporting, or None when no receipt has per-rate figures."""
    if not tally["receipts"]:
        return None
    return {
        "accuracy": tally["correct"] / tally["scored"],
        "correct": tally["correct"],
        "scored": tally["scored"],
        "receipts_fully_correct": {"count": tally["receipts_correct"], "n": tally["receipts"]},
        "extra_rates": tally["extra_rates"],
    }


# --------------------------------------------------------------------------- #
# Extraction (with a per-image cache so scorer iteration is free)
# --------------------------------------------------------------------------- #
def _slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower())


def _model_of(settings: Settings) -> str:
    if settings.llm_provider == "anthropic":
        return settings.anthropic_model
    if settings.llm_provider == "ollama":
        return settings.ollama_model
    if settings.llm_provider == "mistral":
        return settings.mistral_model
    return settings.openai_model


def _set_model(settings: Settings, model: str) -> None:
    """Point the provider already set on `settings` at this model."""
    if settings.llm_provider == "anthropic":
        settings.anthropic_model = model
    elif settings.llm_provider == "ollama":
        settings.ollama_model = model
    elif settings.llm_provider == "mistral":
        settings.mistral_model = model
    else:
        settings.openai_model = model


def read_receipt(
    path: Path, settings: Settings, today: datetime.date, *, use_cache: bool
) -> tuple[ExtractionResult, dict[str, Any]]:
    """One image's read plus its trace (latency/tokens/cost), mirroring the /extract date
    re-read + year-repair steps. Cached unless --refresh.

    This is the only read path, shared with eval_models.py, so RESULTS.md and the model
    matrix score the same reads. The model is non-deterministic: separate passes once made
    the two reports disagree over a single vendor read (D50)."""
    cache = CACHE_DIR / f"{path.stem}.{settings.llm_provider}.{_slug(_model_of(settings))}.models.json"
    if use_cache and cache.exists():
        blob = json.loads(cache.read_text(encoding="utf-8"))
        read_on = datetime.date.fromtimestamp(cache.stat().st_mtime).isoformat()
        trace = {**blob["trace"], "read_date": read_on}
        # The tokens were measured when the read was made; the cost is tokens times the price
        # table, so it's worked out again and a price correction reaches saved reads too.
        if trace.get("input_tokens") or trace.get("output_tokens"):
            trace["est_cost_usd"] = price_usd(
                trace.get("model") or _model_of(settings),
                int(trace.get("input_tokens") or 0), int(trace.get("output_tokens") or 0),
            )
        return ExtractionResult.model_validate(blob["result"]), trace

    image_bytes = path.read_bytes()
    result, oriented, trace = extraction.extract_receipt(image_bytes, path.name, settings)

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
    cache.write_text(
        json.dumps({"result": result.model_dump(mode="json"), "trace": trace}),
        encoding="utf-8",
    )
    return result, {**trace, "read_date": today.isoformat()}


def _extract(path: Path, settings: Settings, today: datetime.date, *, use_cache: bool) -> ExtractionResult:
    """The read alone, for callers that don't need its trace."""
    return read_receipt(path, settings, today, use_cache=use_cache)[0]


# --------------------------------------------------------------------------- #
# The frozen held-out set
# --------------------------------------------------------------------------- #
def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_manifest(labels_path: Path, receipts_dir: Path, labels: list[dict[str, Any]]) -> dict[str, Any]:
    """Hashes of the labels and every labelled photo. They reveal nothing about the receipts,
    but they show that the set wasn't changed after it was scored."""
    return {
        "n_receipts": len(labels),
        "labels_sha256": sha256_of(labels_path),
        "receipts_sha256": {l["file"]: sha256_of(receipts_dir / l["file"]) for l in labels},
    }


def check_frozen(test_dir: Path = TEST_DIR) -> list[str]:
    """What stops the test set being scored: nothing frozen, or a change since it was."""
    freeze_path = test_dir / "freeze.json"
    labels_path = test_dir / "labels.json"
    if not freeze_path.exists() or not labels_path.exists():
        return ["The test set isn't frozen yet. Run: python scripts/prepare_test_set.py freeze"]
    frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
    problems = []
    if sha256_of(labels_path) != frozen["labels_sha256"]:
        problems.append("labels.json changed after freezing.")
    for name, digest in frozen["receipts_sha256"].items():
        path = test_dir / "receipts" / name
        if not path.exists():
            problems.append(f"{name} is missing.")
        elif sha256_of(path) != digest:
            problems.append(f"{name} changed after freezing.")
    return problems


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
    ap.add_argument("--metrics-out", default=None, help="where to write metrics.json (default eval/metrics.json)")
    ap.add_argument("--results-out", default=None, help="where to write RESULTS.md (default eval/RESULTS.md)")
    ap.add_argument("--detail-out", default=None, help="where to write results.detail.json (default eval/results.detail.json)")
    ap.add_argument("--test-set", action="store_true", help="score the frozen held-out set in eval/test/")
    args = ap.parse_args()

    if args.test_set:
        if args.refresh or args.limit:
            print("The test set is read once and scored whole, so --refresh and --limit don't apply.")
            return 2
        problems = check_frozen(TEST_DIR)
        if problems:
            print("Can't score the test set:\n  " + "\n  ".join(problems))
            return 2
        args.labels, args.receipts = str(TEST_DIR / "labels.json"), str(TEST_DIR / "receipts")
        args.metrics_out = args.metrics_out or str(TEST_DIR / "metrics.json")
        args.results_out = args.results_out or str(TEST_DIR / "RESULTS.md")
        args.detail_out = args.detail_out or str(TEST_DIR / "results.detail.json")

    # Output paths default to the committed real artifacts, but can be redirected so a
    # mock/CI run (--provider mock) writes throwaway files and never clobbers the real
    # committed metrics.json / RESULTS.md baseline.
    results_md = Path(args.results_out) if args.results_out else RESULTS_MD
    metrics_json = Path(args.metrics_out) if args.metrics_out else METRICS_JSON
    detail_json = Path(args.detail_out) if args.detail_out else DETAIL_JSON

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
        _set_model(settings, args.model)
    if not settings.llm_configured:
        print(f"LLM provider '{settings.llm_provider}' is not configured (no key). "
              "Set it in backend/.env, or run --provider mock.")
        return 2

    today = datetime.date.today()
    print(f"Provider: {settings.llm_provider} | model: {_model_of(settings)}")
    print(f"Receipts: {len(labels)} | cache: {'off (refresh)' if args.refresh else 'on'}\n")

    # tally[field] = [correct, scored]
    tally: dict[str, list[int]] = {f: [0, 0] for f in FIELDS}
    vat_lines_tally = new_vat_lines_tally()  # a separate score: never part of the overall number
    receipts_fully_correct = 0
    details: list[dict[str, Any]] = []
    gate_rows: list[dict[str, Any]] = []   # one per read, for the guardrail metrics
    slice_rows: list[dict[str, Any]] = []  # one per read, for accuracy-by-receipt-type
    read_dates: list[str] = []             # when the scored reads were made, not when scored
    errors: collections.Counter[str] = collections.Counter()  # failed reads, by exception type
    n_missing = 0                          # labelled images not on disk

    for label in labels:
        name = label["file"]
        path = receipts_dir / name
        row: dict[str, Any] = {"file": name}
        if not path.exists():
            print(f"  MISSING  {name} — not in {receipts_dir}")
            details.append({**row, "error": "image missing"})
            n_missing += 1
            continue
        try:
            result, trace = read_receipt(path, settings, today, use_cache=not args.refresh)
            read_dates.append(trace["read_date"])
            fields = receipt_fields.compute(result, CATEGORIES)
            pred = _predict(result, fields)
        except Exception as exc:  # noqa: BLE001 - a failed read scores as all-miss
            print(f"  ERROR    {name}: {exc}")
            traceback.print_exc()
            scored = _score_fields(label, {f: None for f in FIELDS})
            for f, ok in scored.items():
                tally[f][1] += 1
            slice_rows.append({"tags": label.get("tags", []), "scored": scored})
            add_vat_lines(vat_lines_tally, label, None)
            errors[type(exc).__name__] += 1
            details.append({**row, "error": str(exc)})
            continue

        scored = _score_fields(label, pred)
        for f, ok in scored.items():
            tally[f][0] += int(ok)
            tally[f][1] += 1
        all_ok = all(scored.values())
        receipts_fully_correct += int(all_ok)
        per_rate = add_vat_lines(vat_lines_tally, label, fields["breakdown"])
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
        if per_rate and not per_rate["all_correct"]:
            print(f"            per-rate VAT: {per_rate['correct']}/{per_rate['scored']} rates right"
                  + (f", invented rates {per_rate['extra_rates']}" if per_rate["extra_rates"] else ""))

        details.append({
            "file": name,
            "all_correct": all_ok,
            "scored": scored,
            "expected": {f: label[f] for f in FIELDS if f in label},
            "predicted": {f: pred[f] for f in FIELDS},
            **({"per_rate": {**per_rate, "expected": label["vat_lines"], "read": fields["breakdown"]["rates"]}}
               if per_rate else {}),
        })

    # ---- aggregate ----
    def pct(c: int, n: int) -> str:
        return f"{100.0 * c / n:5.1f}%" if n else "   n/a"

    total_correct = sum(t[0] for t in tally.values())
    total_scored = sum(t[1] for t in tally.values())
    n = len([d for d in details if "error" not in d])
    n_errored = sum(errors.values())
    # A failed read counts against the receipts as well as the fields: it can't quietly
    # shrink a denominator. A missing image was never measured, so it's declared and left out.
    n_scored = n + n_errored
    declared = {"n_labelled": n_scored + n_missing, "n_errored": n_errored,
                "n_missing": n_missing, "error_types": dict(errors)}

    print("\n" + "=" * 52)
    print("Field-level accuracy")
    print("-" * 52)
    print(f"{'field':<14}{'accuracy':>10}{'correct/scored':>18}")
    for f in FIELDS:
        c, t = tally[f]
        print(f"{f:<14}{pct(c, t):>10}{f'{c}/{t}':>18}")
    print("-" * 52)
    print(f"{'OVERALL':<14}{pct(total_correct, total_scored):>10}{f'{total_correct}/{total_scored}':>18}")
    print(f"{'receipts 100%':<14}{pct(receipts_fully_correct, n_scored):>10}{f'{receipts_fully_correct}/{n_scored}':>18}")
    print("=" * 52)
    if n_errored or n_missing:
        print(f"DECLARED: {n_errored} failed reads {dict(errors)} scored as misses; "
              f"{n_missing} images missing, left out.")
    per_rate_summary = summarize_vat_lines(vat_lines_tally)
    if per_rate_summary:
        whole = per_rate_summary["receipts_fully_correct"]
        print(f"VAT per rate (separate score): {pct(per_rate_summary['correct'], per_rate_summary['scored'])} "
              f"({per_rate_summary['correct']}/{per_rate_summary['scored']} rates, "
              f"{whole['count']}/{whole['n']} receipts, {per_rate_summary['extra_rates']} invented rates)")

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

    frozen = (json.loads((TEST_DIR / "freeze.json").read_text(encoding="utf-8"))
              if args.test_set else None)
    _write_results_md(settings, tally, total_correct, total_scored, receipts_fully_correct,
                      n, today, routing, calibration, slices, read_dates, declared, frozen,
                      per_rate=per_rate_summary, out=results_md)
    _write_metrics_json(settings, tally, total_correct, total_scored, receipts_fully_correct,
                        n, today, routing, calibration, confusion, slices, read_dates, declared, frozen,
                        per_rate=per_rate_summary, out=metrics_json)
    detail_json.write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {results_md} + {metrics_json.name} (aggregates, "
          f"committable) and {detail_json.name} (per-receipt, git-ignored).")
    return 0


def _per_rate_section(per_rate: dict[str, Any] | None) -> list[str]:
    if not per_rate:
        return []
    whole = per_rate["receipts_fully_correct"]
    return [
        "## VAT per rate",
        "",
        "A separate score, not part of the overall number above, so that number stays comparable "
        "with the development set, which has no per-rate labels. A rate counts as right when its "
        "net and VAT match within €0.02 and its total within €0.01. A receipt counts only when "
        "every rate is right and no extra rate appears.",
        "",
        "| Measure | Accuracy | Correct / scored |",
        "|---|---:|---:|",
        f"| Rates right | {100.0 * per_rate['correct'] / per_rate['scored']:.1f}% | "
        f"{per_rate['correct']}/{per_rate['scored']} |",
        f"| Receipts with every rate right | {100.0 * whole['count'] / whole['n']:.1f}% | "
        f"{whole['count']}/{whole['n']} |",
        f"| Rates invented | {per_rate['extra_rates']} | |",
        "",
    ]


def _write_results_md(settings, tally, total_correct, total_scored,
                      fully_correct, n, today, routing, calibration, slices, read_dates, declared, frozen,
                      *, per_rate=None, out: Path) -> None:
    def pct(c, t):
        return f"{100.0 * c / t:.1f}%" if t else "n/a"

    def rpct(v):
        return "n/a" if v is None else f"{100.0 * v:.0f}%"

    model = _model_of(settings)
    n_scored = n + declared["n_errored"]
    if frozen:
        title = "# Extraction accuracy: held-out test set"
        intro = (f"Field-level accuracy over **{n_scored}** new receipts, kept apart from the development "
                 f"set. Their true values were written and frozen on {frozen['frozen_on']}, before any model "
                 f"read them, and no prompt changed afterwards. Generated by "
                 f"`backend/scripts/eval_extraction.py --test-set`.")
    else:
        title = "# Extraction accuracy"
        intro = (f"Field-level accuracy of the receipt-extraction pipeline over a hand-labelled "
                 f"set of **{n}** real Portuguese receipts (multi-rate VAT, rotated photos, "
                 f"discounts, and a payment-only receipt). Generated by "
                 f"`backend/scripts/eval_extraction.py`.")
    failures = []
    if declared["n_errored"] or declared["n_missing"]:
        failures.append(f"- **Declared gaps:** {declared['n_errored']} of {declared['n_labelled']} labelled "
                        f"receipts failed to read {declared['error_types'] or ''} and score as misses; "
                        f"{declared['n_missing']} images were missing and are left out.")
    for fix in (frozen or {}).get("corrections", []):
        failures.append(f"- **Label corrected after freezing ({fix['date']}):** {fix['reason']}")
    lines = [
        title,
        "",
        intro,
        "",
        f"- **Provider / model:** {settings.llm_provider} · `{model}`",
        f"- **Scored on:** {today.isoformat()}, using reads made {min(read_dates)} to {max(read_dates)}",
        *failures,
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
        f"| Receipts fully correct | {pct(fully_correct, n_scored)} | {fully_correct}/{n_scored} |",
        "",
        "> Notes: `total` is the amount paid after discounts; `vat_amount`/`vat_rate` "
        "are scored only on receipts that print a VAT table (dominant rate for the "
        "single-rate column); vendor matching is fuzzy (merchant or payment processor).",
        "",
        *_per_rate_section(per_rate),
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
    out.write_text("\n".join(lines), encoding="utf-8")


def _write_metrics_json(settings, tally, total_correct, total_scored,
                        fully_correct, n, today, routing, calibration, confusion, slices, read_dates,
                        declared, frozen, *, per_rate=None, out: Path) -> None:
    """Aggregate metrics for the API/dashboard. Aggregates only — no receipt data —
    so it is safe to commit."""
    data = {
        "provider": settings.llm_provider,
        "model": _model_of(settings),
        "run_date": today.isoformat(),
        "reads_from": min(read_dates),
        "reads_to": max(read_dates),
        "set": "held_out_test" if frozen else "development",
        "n_receipts": n,
        **declared,
        "fields": {
            f: {"accuracy": (tally[f][0] / tally[f][1]) if tally[f][1] else None,
                "correct": tally[f][0], "scored": tally[f][1]}
            for f in FIELDS
        },
        "overall": {
            "accuracy": (total_correct / total_scored) if total_scored else None,
            "correct": total_correct, "scored": total_scored,
        },
        "receipts_fully_correct": {"count": fully_correct, "n": n + declared["n_errored"]},
        **({"per_rate_vat": per_rate} if per_rate else {}),
        "guardrails": routing,
        "calibration": calibration,
        "confusion": confusion,
        "slices": slices,
    }
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
