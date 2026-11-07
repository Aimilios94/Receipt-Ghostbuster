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

A run only updates the rows of the models it names: every other model in models.json
keeps its row and its own measurement record, and a replaced row's headline moves to
that model's history. Pass --replace-all to start a new matrix. A --limit run is a
smoke test and writes nothing.

A read that fails is declared, never dropped: its fields score as misses, and the row
records how many reads errored and why.

Usage (from backend/, with the relevant keys in backend/.env):
    python scripts/eval_models.py \
        --models openai:gpt-5-mini openai:gpt-4o anthropic:claude-haiku-4-5

Each (model, image) read is cached under eval/.cache/*.models.json, so the first
run spends real API tokens (a comparison across N models over M receipts is
inherently a real-spend run) and re-runs are free.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import platform
import re
import subprocess
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


_slug = ev._slug
_model_of = ev._model_of


def _extract_with_trace(
    path: Path, settings: Settings, today: datetime.date, *, use_cache: bool
) -> tuple[ExtractionResult, dict[str, Any]]:
    """The shared read path, so the matrix and RESULTS.md score the same reads. Combined
    result+trace cache, so re-runs don't re-spend and still report the real latency/cost
    from the first read."""
    return ev.read_receipt(path, settings, today, use_cache=use_cache)


# --------------------------------------------------------------------------- #
# Measurement record
# --------------------------------------------------------------------------- #
def _git_commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=ev.BACKEND, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        head = git("rev-parse", "--short", "HEAD")
        return f"{head}+uncommitted" if git("status", "--porcelain", "--untracked-files=no") else head
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _ollama_version(settings: Settings) -> str | None:
    import httpx

    root = settings.ollama_base_url.rsplit("/v1", 1)[0]
    try:
        return httpx.get(f"{root}/api/version", timeout=3).json().get("version")
    except (httpx.HTTPError, ValueError):
        return None


def _provenance(
    provider: str, model: str, settings: Settings, today: datetime.date, read_dates: list[str]
) -> dict[str, Any]:
    runtime = f"Python {platform.python_version()}"
    if provider == "ollama":
        runtime += f" · Ollama {_ollama_version(settings) or 'unknown'}"
    return {
        "run_date": today.isoformat(),
        "reads_from": min(read_dates) if read_dates else None,
        "reads_to": max(read_dates) if read_dates else None,
        "commit": _git_commit(),
        "command": f"python backend/scripts/eval_models.py --models {provider}:{model}",
        "machine": f"{platform.platform()} · {os.cpu_count()} logical CPUs",
        "runtime": runtime,
    }


# --------------------------------------------------------------------------- #
# One model's run over the labelled set
# --------------------------------------------------------------------------- #
def _run_model(
    provider: str, model: str, labels: list[dict[str, Any]], receipts_dir: Path,
    today: datetime.date, *, use_cache: bool,
) -> dict[str, Any] | None:
    settings = Settings(_env_file=str(ev.BACKEND / ".env"))
    settings.llm_provider = provider
    ev._set_model(settings, model)
    if not settings.llm_configured:
        print(f"  SKIP {provider}:{model} — provider not configured (no key).")
        return None

    print(f"\n=== {provider} : {model} ===")
    tally: dict[str, list[int]] = {f: [0, 0] for f in ev.FIELDS}
    vat_lines_tally = ev.new_vat_lines_tally()
    gate_rows: list[dict[str, Any]] = []
    slice_rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    costs: list[float] = []
    fell_back = 0
    fully_correct = 0
    n = 0
    n_missing = 0
    errors: collections.Counter[str] = collections.Counter()
    read_dates: list[str] = []

    for label in labels:
        name = label["file"]
        path = receipts_dir / name
        if not path.exists():
            print(f"  MISSING  {name}")
            n_missing += 1
            continue
        try:
            result, trace = _extract_with_trace(path, settings, today, use_cache=use_cache)
            fields = receipt_fields.compute(result, ev.CATEGORIES)
            pred = ev._predict(result, fields)
        except Exception as exc:  # noqa: BLE001 - a failed read scores all-miss
            print(f"  ERROR    {name}: {exc}")
            traceback.print_exc()
            errors[type(exc).__name__] += 1
            missed = ev._score_fields(label, {f: None for f in ev.FIELDS})
            for f in missed:
                tally[f][1] += 1
            slice_rows.append({"tags": label.get("tags", []), "scored": missed})
            ev.add_vat_lines(vat_lines_tally, label, None)
            continue

        n += 1
        read_dates.append(trace["read_date"])
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
        ev.add_vat_lines(vat_lines_tally, label, fields["breakdown"])

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
    n_errored = sum(errors.values())
    routing = eval_metrics.routing_scores(gate_rows)
    slices = eval_metrics.slice_accuracy(slice_rows)
    per_rate = ev.summarize_vat_lines(vat_lines_tally)
    return {
        "provider": provider,
        "model": model,
        "n_receipts": n,
        "n_labelled": n + n_errored + n_missing,
        "n_errored": n_errored,
        "n_missing": n_missing,
        "error_types": dict(errors),
        "provenance": _provenance(provider, model, settings, today, read_dates),
        "fields": {f: {"accuracy": (tally[f][0] / tally[f][1]) if tally[f][1] else None,
                       "correct": tally[f][0], "scored": tally[f][1]} for f in ev.FIELDS},
        "overall": {"accuracy": (total_correct / total_scored) if total_scored else None,
                    "correct": total_correct, "scored": total_scored},
        "receipts_fully_correct": {"count": fully_correct, "n": n + n_errored},
        **({"per_rate_vat": per_rate} if per_rate else {}),
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


def merge_results(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Replace the rows of the models just run and keep every other row untouched.
    A replaced row's headline moves to the model's history, so repeat runs stay visible.
    Scoring the same reads again with the same result isn't a new run, so it adds nothing."""
    def key(r: dict[str, Any]) -> tuple[str, str]:
        return r["provider"], r["model"]

    fresh = {key(r): r for r in new}
    merged: list[dict[str, Any]] = []
    for old in existing:
        replacement = fresh.pop(key(old), None)
        if replacement is None:
            merged.append(old)
            continue
        before, after = old.get("provenance") or {}, replacement.get("provenance") or {}
        same_reads = bool(before.get("reads_from")) and all(
            before.get(k) == after.get(k) for k in ("reads_from", "reads_to")
        ) and (old["overall"]["correct"], old["overall"]["scored"]) == (
            replacement["overall"]["correct"], replacement["overall"]["scored"]
        )
        if same_reads:
            merged.append({**replacement, "history": old.get("history", [])}
                          if old.get("history") else replacement)
            continue
        earlier = {
            "run_date": before.get("run_date"),
            "reads_from": before.get("reads_from"),
            "reads_to": before.get("reads_to"),
            "accuracy": old["overall"]["accuracy"],
            "correct": old["overall"]["correct"],
            "scored": old["overall"]["scored"],
            "n_receipts": old["n_receipts"],
            "n_errored": old.get("n_errored", 0),
        }
        merged.append({**replacement, "history": [*old.get("history", []), earlier]})
    return merged + list(fresh.values())


def _state(r: dict[str, Any]) -> str:
    if r.get("n_errored") or r.get("n_missing"):
        return "MEASURED, partial"
    return (r.get("provenance") or {}).get("state", "MEASURED")


def _reads_dated(prov: dict[str, Any]) -> str:
    first, last = prov.get("reads_from"), prov.get("reads_to")
    if not first:
        return prov.get("run_date") or "NO_DATA (not recorded)"
    return first if first == last else f"{first} to {last}"


def _write_models_md(doc: dict[str, Any], *, path: Path = MODELS_MD) -> None:
    results = doc["models"]
    n = doc["n_receipts"]

    def label(r):
        return f"`{r['model']}`"

    lines = [
        "# Model comparison — receipt extraction",
        "",
        f"The same shipped pipeline (`extraction.extract_receipt` + the deterministic "
        f"`receipt_fields.compute` logic + the shipped review gate) run across models over "
        f"{doc.get('set_description') or f'the hand-labelled set of **{n}** real Portuguese receipts'}. "
        f"Generated by `backend/scripts/eval_models.py`.",
        "",
        f"- **Last updated:** {doc['run_date']}. Models are measured separately, so each row "
        f"carries its own date in the measurement record below.",
        f"- **Honest caveat:** n={n} is a small set, so differences of a few points are "
        f"**not statistically significant** — read this as a direction, not a leaderboard. "
        f"Latency/cost are per-receipt estimates (summed across every orientation read).",
        *[f"- {note}" for note in doc.get("notes", [])],
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
    for r in results:
        if r.get("n_errored"):
            causes = ", ".join(f"{k} ×{v}" for k, v in r.get("error_types", {}).items())
            lines += ["", f"{label(r)}: {r['n_errored']} read(s) errored ({causes}); their fields "
                          f"count as misses, and latency/cost/guardrails cover the {r['n_receipts']} "
                          f"successful reads only."]
        if r.get("n_missing"):
            lines += ["", f"{label(r)}: {r['n_missing']} labelled receipt(s) NO_DATA (image not on "
                          f"disk for this run); they are left out of its denominators."]
    for r in results:
        for h in r.get("history", []):
            errored = f", {h['n_errored']} read(s) errored" if h.get("n_errored") else ""
            made = f", from reads made {_reads_dated(h)}" if h.get("reads_from") else ""
            lines += ["", f"Earlier result for {label(r)}, scored {h.get('run_date') or 'on an unrecorded date'}{made}: "
                          f"{_pct(h['accuracy'])} ({h['correct']}/{h['scored']} fields, "
                          f"{h['n_receipts']} reads{errored})."]
    per_rate_rows = [r for r in results if r.get("per_rate_vat")]
    if per_rate_rows:
        lines += [
            "",
            "## VAT per rate",
            "",
            "A separate score, not part of Overall. A rate counts as right when its net and VAT match "
            "within €0.02 and its total within €0.01. A receipt counts only when every rate is right "
            "and no extra rate appears.",
            "",
            "| Model | Rates right | Receipts with every rate right | Rates invented |",
            "|---|---:|---:|---:|",
        ]
        for r in per_rate_rows:
            p = r["per_rate_vat"]
            whole = p["receipts_fully_correct"]
            lines.append(f"| {label(r)} | {_pct(p['accuracy'])} ({p['correct']}/{p['scored']}) | "
                         f"{whole['count']}/{whole['n']} | {p['extra_rates']} |")
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
    for footnote in doc.get("footnotes", []):
        lines += ["", footnote]

    no_data = "NO_DATA (not recorded)"
    lines += [
        "",
        "## Measurement record",
        "",
        "How each row was produced. An unrecorded value is stated as `NO_DATA`, never left blank.",
        "",
        "| Model | State | Read / labelled | Reads dated | Commit | Machine | Runtime | Command |",
        "|---|---|---:|---|---|---|---|---|",
    ]
    for r in results:
        prov = r.get("provenance") or {}
        labelled = r.get("n_labelled", r["n_receipts"])
        command = prov.get("command")
        lines.append(
            f"| {label(r)} | {_state(r)} | {r['n_receipts']}/{labelled} | {_reads_dated(prov)} | "
            f"{prov.get('commit') or no_data} | {prov.get('machine') or no_data} | "
            f"{prov.get('runtime') or no_data} | {f'`{command}`' if command else no_data} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_doc(
    new: list[dict[str, Any]], existing_doc: dict[str, Any], today: datetime.date, *, replace_all: bool
) -> dict[str, Any]:
    models = new if replace_all else merge_results(existing_doc.get("models", []), new)
    return {
        "run_date": today.isoformat(),
        "n_receipts": max(r.get("n_labelled", r["n_receipts"]) for r in models),
        "notes": existing_doc.get("notes", []),
        "footnotes": existing_doc.get("footnotes", []),
        "models": models,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Multi-model receipt-extraction comparison.")
    ap.add_argument("--models", nargs="+", required=True,
                    help="provider:model specs, e.g. openai:gpt-5-mini anthropic:claude-haiku-4-5")
    ap.add_argument("--labels", default=str(ev.LABELS), help="path to labels.json")
    ap.add_argument("--receipts", default=str(ev.RECEIPTS_DIR), help="dir of receipt images")
    ap.add_argument("--limit", type=int, default=None, help="only the first N receipts")
    ap.add_argument("--refresh", action="store_true", help="ignore cache, re-call the LLMs")
    ap.add_argument("--replace-all", action="store_true",
                    help="start a new matrix instead of updating only the models named here")
    ap.add_argument("--test-set", action="store_true",
                    help="use the frozen held-out set and write its own matrix in eval/test/")
    args = ap.parse_args()

    models_md, models_json = MODELS_MD, MODELS_JSON
    if args.test_set:
        if args.refresh or args.limit:
            print("The test set is read once and scored whole, so --refresh and --limit don't apply.")
            return 2
        problems = ev.check_frozen(ev.TEST_DIR)
        if problems:
            print("Can't score the test set:\n  " + "\n  ".join(problems))
            return 2
        args.labels, args.receipts = str(ev.TEST_DIR / "labels.json"), str(ev.TEST_DIR / "receipts")
        models_md, models_json = ev.TEST_DIR / "MODELS.md", ev.TEST_DIR / "models.json"

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
            if args.test_set:
                r["provenance"]["command"] += " --test-set"
            results.append(r)

    if not results:
        print("\nNo model produced a result — leaving MODELS.md untouched.")
        return 1

    if args.limit:
        print(f"\n--limit run: smoke test only, {MODELS_MD.name} and {MODELS_JSON.name} left untouched.")
        return 0

    existing = json.loads(models_json.read_text(encoding="utf-8")) if models_json.exists() else {}
    doc = build_doc(results, existing, today, replace_all=args.replace_all)
    if args.test_set:
        doc["set_description"] = (f"**{doc['n_receipts']}** new receipts held out from the development set, "
                                  f"labelled and frozen before any model read them")
    _write_models_md(doc, path=models_md)
    models_json.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"\nWrote {models_md} + {models_json.name} "
          f"({len(results)} model(s) updated, {len(doc['models'])} in the matrix).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
