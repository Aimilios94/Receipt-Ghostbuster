"""Run the receipt-extraction eval as a LangSmith EXPERIMENT (opt-in).

This uploads the hand-labelled receipt set as a LangSmith Dataset and runs the
shipped extraction pipeline over it as a tracked Experiment, scoring each field
with the SAME matchers the offline harness uses (scripts/eval_extraction.py). The
result is a real experiment run in the LangSmith UI — per-example traces, scores,
and comparisons across runs — complementing the self-contained RESULTS.md.

Strictly OPT-IN. It does nothing unless LangSmith is configured:
    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=ls__...
    LANGSMITH_PROJECT=receipt-ghostbuster     (optional)

Run (from backend/):
    python scripts/langsmith_eval.py

Reads are served from the same per-image cache as the offline eval, so re-runs
don't re-spend API calls. NOTE: with tracing on, the receipt images/prompts are
sent to LangSmith's cloud — intended, but see the privacy note in .env.example.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))        # so we can reuse the offline harness helpers
sys.path.insert(0, str(HERE.parent))  # so `app` imports resolve

import eval_extraction as ev  # noqa: E402  (reuses _extract/_predict/_score_fields/CATEGORIES/FIELDS)
from app.config import Settings  # noqa: E402
from app.services import receipt_fields  # noqa: E402

DATASET = "receipt-ghostbuster-extraction"


def _configured() -> bool:
    return os.getenv("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes") and bool(
        os.getenv("LANGSMITH_API_KEY")
    )


def main() -> int:
    load_env = HERE.parent / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(load_env)
    except Exception:  # noqa: BLE001
        pass

    if not _configured():
        print(
            "LangSmith is not enabled. This script is opt-in — set in backend/.env:\n"
            "  LANGSMITH_TRACING=true\n"
            "  LANGSMITH_API_KEY=ls__...\n"
            "  LANGSMITH_PROJECT=receipt-ghostbuster   (optional)\n"
            "Then re-run. (The self-contained eval, scripts/eval_extraction.py, needs none of this.)"
        )
        return 2

    if not ev.LABELS.exists():
        print(f"No labels at {ev.LABELS}. See backend/eval/README.md.")
        return 2
    labels = json.loads(ev.LABELS.read_text(encoding="utf-8"))

    settings = Settings(_env_file=str(ev.BACKEND / ".env"))
    today = datetime.date.today()

    try:
        from langsmith import Client, evaluate
    except Exception as exc:  # noqa: BLE001
        print(f"langsmith not installed ({exc}). pip install langsmith")
        return 2

    client = Client()

    # 1) Ensure the dataset exists and is populated (idempotent).
    try:
        ds = client.read_dataset(dataset_name=DATASET)
    except Exception:  # noqa: BLE001 - not found -> create
        ds = client.create_dataset(dataset_name=DATASET, description="Hand-labelled PT receipts")
    if not list(client.list_examples(dataset_id=ds.id)):
        client.create_examples(
            dataset_id=ds.id,
            inputs=[{"file": lbl["file"]} for lbl in labels],
            outputs=[{k: lbl[k] for k in lbl if k != "file"} for lbl in labels],
        )
        print(f"Uploaded {len(labels)} examples to dataset '{DATASET}'.")
    else:
        print(f"Dataset '{DATASET}' already populated — reusing it.")

    # 2) The system under test: the shipped pipeline, reusing the offline cache.
    def target(inputs: dict) -> dict:
        path = ev.RECEIPTS_DIR / inputs["file"]
        result = ev._extract(path, settings, today, use_cache=True)
        fields = receipt_fields.compute(result, ev.CATEGORIES)
        return ev._predict(result, fields)

    # 3) Evaluators — the SAME field matchers as the offline harness.
    def overall(run, example):
        scored = ev._score_fields(example.outputs or {}, run.outputs or {})
        n = len(scored)
        return {"key": "overall_accuracy", "score": (sum(scored.values()) / n) if n else None}

    def make_field_eval(field: str):
        def _e(run, example):
            ref, pred = example.outputs or {}, run.outputs or {}
            if field not in ref:
                return {"key": field, "score": None}
            scored = ev._score_fields({field: ref[field], "vendor_alt": ref.get("vendor_alt", [])}, pred)
            return {"key": field, "score": 1.0 if scored.get(field) else 0.0}

        return _e

    evaluators = [overall] + [make_field_eval(f) for f in ev.FIELDS]

    print(f"Running experiment over '{DATASET}' ({len(labels)} receipts)…")
    results = evaluate(
        target,
        data=DATASET,
        evaluators=evaluators,
        experiment_prefix="rg-extraction",
        client=client,
    )
    url = getattr(results, "experiment_url", None) or getattr(results, "url", None)
    print("Done. View it in LangSmith" + (f": {url}" if url else " (see the Experiments tab)."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
