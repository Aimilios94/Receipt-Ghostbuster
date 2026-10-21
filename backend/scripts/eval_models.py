"""Multi-model extraction comparison.

Runs the SAME shipped pipeline the single-model harness uses (`eval_extraction`)
across several provider/model combinations and produces a side-by-side matrix of
**accuracy x latency x cost** — the question "which model should read receipts?"
answered with data instead of intuition (it's how the current gpt-5-mini choice was
made; see DECISIONS D27).

It reuses `eval_extraction`'s scorers, field list, category set and the shared
`eval_metrics` slice/guardrail math, so a model is scored identically to the
canonical run. The only thing it does that the single-model harness doesn't: it
captures each read's observability **trace** (latency, tokens, estimated cost) from
`extraction.extract_receipt`, so the comparison can report real latency/cost, not
just accuracy.

Outputs (committable aggregates, no per-receipt data):
  * backend/eval/MODELS.md    — human-readable comparison matrix
  * backend/eval/models.json  — machine-readable, same numbers

This leaves RESULTS.md / metrics.json (the single shipped model, served to the
in-app Model & Evals page) untouched.

Usage (from backend/, with the relevant keys in backend/.env):
    python scripts/eval_models.py \
        --models openai:gpt-5-mini openai:gpt-4o anthropic:claude-haiku-4-5

Each (model, image) read is cached under eval/.cache/*.models.json, so the first
run spends real API tokens (a comparison across N models over M receipts is
inherently a real-spend run) and re-runs are free.
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

# Reuse the canonical harness wholesale: its scorers, field list, category set,
# paths and the app-service imports it already wired up.
import eval_extraction as ev  # noqa: E402  (same dir)

eval_metrics = ev.eval_metrics
extraction = ev.extraction
receipt_fields = ev.receipt_fields
gating = ev.gating
validation = ev.validation
ExtractionResult = ev.ExtractionResult
Settings = ev.Settings

MODELS_MD = ev.EVAL_DIR / "MODELS.md"
MODELS_JSON = ev.EVAL_DIR / "models.json"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _pctl(xs: list[float], p: float) -> float:
    """Linear-interpolated percentile (p in [0,1]); 0.0 for an empty list."""
    if not xs:
        return 0.0
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def _slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower())


def _model_of(settings: Settings) -> str:
    return settings.anthropic_model if settings.llm_provider == "anthropic" else settings.openai_model


def _extract_with_trace(
    path: Path, settings: Settings, today: datetime.date, *, use_cache: bool
) -> tuple[ExtractionResult, dict[str, Any]]:
    """Like eval_extraction._extract but also returns the observability trace
    (latency/tokens/cost). Combined result+trace cache, so re-runs don't re-spend
    and still report the real latency/cost from the first read."""
    model = _model_of(settings)
    cache = ev.CACHE_DIR / f"{path.stem}.{settings.llm_provider}.{_slug(model)}.models.json"
    if use_cache and cache.exists():
        blob = json.loads(cache.read_text(encoding="utf-8"))
        return ExtractionResult.model_validate(blob["result"]), blob["trace"]

    image_bytes = path.read_bytes()
    result, oriented, trace = extraction.extract_receipt(image_bytes, path.name, settings)

    # Mirror the router / single-model harness: re-read a suspicious date, then
    # deterministically repair a misread year, so the number reflects the shipped
    # pipeline rather than a stripped-down read.
    d = result.date
    if d is None or d > today or (today - d).days > validation.MAX_AGE_DAYS:
        better = extraction.reread_date(oriented, path.name, settings, today)
        if better is not None and better != result.date:
            result.date = better
    if result.date is not None:
        fixed = validation.repair_year(result.date, today)
        if fixed is not None:
            result.date = fixed

    ev.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"result": result.model_dump(mode="json"), "trace": trace}),
        encoding="utf-8",
    )
    return result, trace


# --------------------------------------------------------------------------- #
# One model's run over the labelled set
# --------------------------------------------------------------------------- #
def _run_model(
    provider: str, model: str, labels: list[dict[str, Any]], receipts_dir: Path,
    today: datetime.date, *, use_cache: bool,
) -> dict[str, Any] | None:
    settings = Settings(_env_file=str(ev.BACKEND / ".env"))
    settings.llm_provider = provider
    if provider == "anthropic":
        settings.anthropic_model = model
    else:
        settings.openai_model = model
    if not settings.llm_configured:
        print(f"  SKIP {provider}:{model} — provider not configured (no key).")
        return None

    print(f"\n=== {provider} : {model} ===")
    tally: dict[str, list[int]] = {f: [0, 0] for f in ev.FIELDS}
    gate_rows: list[dict[str, Any]] = []
    slice_rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    costs: list[float] = []
    fell_back = 0
    fully_correct = 0
    n = 0

    for label in labels:
        name = label["file"]
        path = receipts_dir / name
        if not path.exists():
            print(f"  MISSING  {name}")
            continue
        try:
            result, trace = _extract_with_trace(path, settings, today, use_cache=use_cache)
            fields = receipt_fields.compute(result, ev.CATEGORIES)
            pred = ev._predict(result, fields)
        except Exception as exc:  # noqa: BLE001 - a failed read scores all-miss
            print(f"  ERROR    {name}: {exc}")
            traceback.print_exc()
            for f in ev._score_fields(label, {f: None for f in ev.FIELDS}):
                tally[f][1] += 1
            continue

        n += 1
        latencies.append(float(trace.get("latency_ms", 0)))
        costs.append(float(trace.get("est_cost_usd", 0.0)))
        fell_back += int(bool(trace.get("fell_back")))

        scored = ev._score_fields(label, pred)
        for f, ok in scored.items():
            tally[f][0] += int(ok)
            tally[f][1] += 1
        all_ok = all(scored.values())
        fully_correct += int(all_ok)
        slice_rows.append({"tags": label.get("tags", []), "scored": scored})

        check = validation.validate_receipt(result, confidence_threshold=settings.confidence_threshold)
        gate = gating.decide_gate(result, check, fields, settings, today)
        gate_rows.append({
            "file": name,
            "expected_gate": label.get("expected_gate"),
            "predicted_gate": ev._GATE_MAP.get(gate["gated_to"]),
            "field_correct": all_ok if scored else None,
            "confidence": result.confidence,
            "guardrails_fired": gate["guardrails_fired"],
        })
        print(f"  {'OK  ' if all_ok else 'MISS'}  {name:<22} "
              f"{trace.get('latency_ms', 0)/1000:.1f}s  ${trace.get('est_cost_usd', 0.0):.4f}"
              + ("" if all_ok else "  wrong: " + ", ".join(f for f, ok in scored.items() if not ok)))

    if n == 0:
        print(f"  no receipts read for {provider}:{model} — excluded from the matrix.")
        return None

    total_correct = sum(t[0] for t in tally.values())
    total_scored = sum(t[1] for t in tally.values())
    routing = eval_metrics.routing_scores(gate_rows)
    slices = eval_metrics.slice_accuracy(slice_rows)
    return {
        "provider": provider,
        "model": model,
        "n_receipts": n,
        "fields": {f: {"accuracy": (tally[f][0] / tally[f][1]) if tally[f][1] else None,
                       "correct": tally[f][0], "scored": tally[f][1]} for f in ev.FIELDS},
        "overall": {"accuracy": (total_correct / total_scored) if total_scored else None,
                    "correct": total_correct, "scored": total_scored},
        "receipts_fully_correct": {"count": fully_correct, "n": n},
        "latency_ms": {"p50": round(_pctl(latencies, 0.5)), "p95": round(_pctl(latencies, 0.95)),
                       "avg": round(sum(latencies) / n)},
        "cost_usd": {"total": round(sum(costs), 6), "avg_per_read": round(sum(costs) / n, 6)},
        "fell_back": fell_back,
        "guardrails": {"false_auto_posts": routing["false_auto_posts"],
                       "false_auto_post_rate": routing["false_auto_post_rate"],
                       "over_review_rate": routing["over_review_rate"]},
        "slices": slices,
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100.0 * x:.1f}%"


def _rpct(x: float | None) -> str:
    return "n/a" if x is None else f"{100.0 * x:.0f}%"


def _write_models_md(results: list[dict[str, Any]], today: datetime.date, n: int) -> None:
    def label(r):
        return f"`{r['model']}`"

    lines = [
        "# Model comparison — receipt extraction",
        "",
        f"The same shipped pipeline (`extraction.extract_receipt` + the deterministic "
        f"`receipt_fields.compute` logic + the shipped review gate) run across models over "
        f"the hand-labelled set of **{n}** real Portuguese receipts. Generated by "
        f"`backend/scripts/eval_models.py`.",
        "",
        f"- **Run date:** {today.isoformat()}",
        f"- **Honest caveat:** n={n} is a small set, so differences of a few points are "
        f"**not statistically significant** — read this as a direction, not a leaderboard. "
        f"Latency/cost are per-receipt estimates (summed across every orientation read).",
        "",
        "## Accuracy",
        "",
        "| Model | Overall | vendor | date | total | vat amt | vat rate | category | Receipts 100% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        f = r["fields"]
        lines.append(
            f"| {label(r)} | **{_pct(r['overall']['accuracy'])}** | "
            f"{_pct(f['vendor']['accuracy'])} | {_pct(f['date']['accuracy'])} | "
            f"{_pct(f['total']['accuracy'])} | {_pct(f['vat_amount']['accuracy'])} | "
            f"{_pct(f['vat_rate']['accuracy'])} | {_pct(f['category']['accuracy'])} | "
            f"{r['receipts_fully_correct']['count']}/{r['receipts_fully_correct']['n']} |"
        )
    lines += [
        "",
        "## Latency, cost & reliability",
        "",
        "| Model | Latency p50 | Latency p95 | Avg | $/read | Total $ | Fell back | False auto-posts | Over-review |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lat, cost, g = r["latency_ms"], r["cost_usd"], r["guardrails"]
        lines.append(
            f"| {label(r)} | {lat['p50']/1000:.1f}s | {lat['p95']/1000:.1f}s | {lat['avg']/1000:.1f}s | "
            f"${cost['avg_per_read']:.4f} | ${cost['total']:.4f} | {r['fell_back']} | "
            f"{g['false_auto_posts']} ({_rpct(g['false_auto_post_rate'])}) | {_rpct(g['over_review_rate'])} |"
        )

    # Accuracy by receipt type, models as columns (only tags that appear).
    all_tags: list[str] = []
    for r in results:
        for tag in r["slices"]:
            if tag not in all_tags:
                all_tags.append(tag)
    if all_tags:
        all_tags.sort()
        lines += [
            "",
            "## Accuracy by receipt type",
            "",
            "Field-level accuracy per receipt characteristic (a receipt counts toward every "
            "tag it carries) — so a strong average can't hide a weak slice.",
            "",
            "| Receipt type | " + " | ".join(label(r) for r in results) + " |",
            "|---|" + "---:|" * len(results),
        ]
        for tag in all_tags:
            cells = []
            for r in results:
                s = r["slices"].get(tag)
                cells.append(_pct(s["accuracy"]) if s else "—")
            lines.append(f"| {tag} | " + " | ".join(cells) + " |")
    lines.append("")
    MODELS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Multi-model receipt-extraction comparison.")
    ap.add_argument("--models", nargs="+", required=True,
                    help="provider:model specs, e.g. openai:gpt-5-mini anthropic:claude-haiku-4-5")
    ap.add_argument("--labels", default=str(ev.LABELS), help="path to labels.json")
    ap.add_argument("--receipts", default=str(ev.RECEIPTS_DIR), help="dir of receipt images")
    ap.add_argument("--limit", type=int, default=None, help="only the first N receipts")
    ap.add_argument("--refresh", action="store_true", help="ignore cache, re-call the LLMs")
    args = ap.parse_args()

    labels_path = Path(args.labels)
    if not labels_path.exists():
        print(f"No labels file at {labels_path}. See backend/eval/README.md.")
        return 2
    labels: list[dict[str, Any]] = json.loads(labels_path.read_text(encoding="utf-8"))
    if args.limit:
        labels = labels[: args.limit]
    receipts_dir = Path(args.receipts)
    today = datetime.date.today()

    specs: list[tuple[str, str]] = []
    for spec in args.models:
        if ":" not in spec:
            print(f"Bad --models spec '{spec}'; expected provider:model.")
            return 2
        provider, model = spec.split(":", 1)
        specs.append((provider.strip().lower(), model.strip()))

    results: list[dict[str, Any]] = []
    for provider, model in specs:
        r = _run_model(provider, model, labels, receipts_dir, today, use_cache=not args.refresh)
        if r is not None:
            results.append(r)

    if not results:
        print("\nNo model produced a result — leaving MODELS.md untouched.")
        return 1

    n = max(r["n_receipts"] for r in results)
    _write_models_md(results, today, n)
    MODELS_JSON.write_text(
        json.dumps({"run_date": today.isoformat(), "n_receipts": n, "models": results}, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {MODELS_MD.relative_to(ev.BACKEND.parent)} + {MODELS_JSON.name} "
          f"({len(results)} models, {n} receipts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
