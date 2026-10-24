"""Accuracy-regression gate.

Compares a metrics file produced by `eval_extraction.py` against a committed
baseline and fails (non-zero exit) if any tracked metric drops below its baseline
floor minus a tolerance band. This is the gate that keeps a code change from
silently degrading extraction accuracy.

Two ways it runs:

  * **Locally, on the real number** — `eval_extraction.py` reads the git-ignored
    labelled set from its per-image CACHE (deterministic, no API cost, no network)
    and writes `eval/metrics.json`; this script compares it to `eval/baseline.json`.
    Run before committing anything that touches the extraction / VAT / gate code:

        python scripts/eval_extraction.py                 # cached reads, writes metrics.json
        python scripts/check_regression.py                # gate: metrics.json vs baseline.json

  * **In CI, on the mock mechanism** — no secrets and no personal data are available
    in the public runner, so CI runs the harness in `--provider mock` mode (one
    committed synthetic fixture) to a throwaway metrics file and gates it against
    `eval/baseline.mock.json`. That can't verify the real accuracy number, but it
    DOES catch a code change that silently breaks the scoring / VAT / gate pipeline
    (the mock's deterministic score would move).

Why a tolerance band: re-reading the model (`--refresh`) is mildly non-deterministic
(~1pp). On CACHED reads the pipeline is deterministic, so the band only absorbs a
legitimate re-label; a real regression drops well past it. The band is read from the
baseline's `tolerance_pp`.

Pure stdlib (json), no app import — so it is fast and trivially unit-tested.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EVAL_DIR = HERE.parent / "eval"
DEFAULT_METRICS = EVAL_DIR / "metrics.json"
DEFAULT_BASELINE = EVAL_DIR / "baseline.json"

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass


def _field_acc(metrics: dict[str, Any], field: str) -> float | None:
    f = (metrics.get("fields") or {}).get(field)
    return None if f is None else f.get("accuracy")


def _fully_correct(metrics: dict[str, Any]) -> float | None:
    fc = metrics.get("receipts_fully_correct") or {}
    n = fc.get("n") or 0
    return (fc.get("count", 0) / n) if n else None


def check(metrics: dict[str, Any], baseline: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """Return (ok, rows). `ok` is False if any metric regressed past the tolerance."""
    tol = float(baseline.get("tolerance_pp", 1.0)) / 100.0
    rows: list[dict[str, Any]] = []

    def add(name: str, current: float | None, floor: float | None) -> None:
        if floor is None:
            return
        regressed = current is None or current < floor - tol
        rows.append({
            "metric": name,
            "baseline": floor,
            "current": current,
            "floor": floor - tol,
            "ok": not regressed,
        })

    add("overall", (metrics.get("overall") or {}).get("accuracy"), baseline.get("overall_accuracy"))
    for field, floor in (baseline.get("fields") or {}).items():
        add(f"field:{field}", _field_acc(metrics, field), floor)
    if "receipts_fully_correct" in baseline:
        add("receipts_fully_correct", _fully_correct(metrics), baseline["receipts_fully_correct"])

    ok = all(r["ok"] for r in rows)
    return ok, rows


def _fmt(v: float | None) -> str:
    return "  n/a" if v is None else f"{100.0 * v:5.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description="Accuracy-regression gate.")
    ap.add_argument("--metrics", default=str(DEFAULT_METRICS), help="metrics.json from eval_extraction.py")
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="committed baseline floor")
    args = ap.parse_args()

    metrics_path, baseline_path = Path(args.metrics), Path(args.baseline)
    for p, what in ((metrics_path, "metrics"), (baseline_path, "baseline")):
        if not p.exists():
            print(f"ERROR: {what} file not found at {p}")
            return 2
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    ok, rows = check(metrics, baseline)
    tol_pp = float(baseline.get("tolerance_pp", 1.0))

    print(f"Accuracy-regression gate  (tolerance {tol_pp:.1f}pp)")
    print(f"  metrics : {metrics.get('model', '?')} · n={metrics.get('n_receipts', '?')} · {metrics_path}")
    print(f"  baseline: {baseline.get('model', '?')} · n={baseline.get('n_receipts', '?')} · {baseline_path}")
    print("-" * 60)
    print(f"  {'metric':<28}{'baseline':>9}{'current':>9}{'min':>9}  ")
    for r in rows:
        mark = "ok  " if r["ok"] else "FAIL"
        print(f"  {r['metric']:<28}{_fmt(r['baseline']):>9}{_fmt(r['current']):>9}{_fmt(r['floor']):>9}  {mark}")
    print("-" * 60)

    # A grown/changed set is not a regression, but the baseline should be refreshed
    # deliberately with the metrics it came from — surface it as a non-fatal note.
    if metrics.get("n_receipts") != baseline.get("n_receipts"):
        print(f"NOTE: metrics n={metrics.get('n_receipts')} != baseline n={baseline.get('n_receipts')} "
              "— refresh baseline.json deliberately when the set changes.")

    if ok:
        print("PASS — no metric regressed past the tolerance band.")
        return 0
    print("FAIL — a metric dropped below its baseline floor. See the FAIL rows above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
