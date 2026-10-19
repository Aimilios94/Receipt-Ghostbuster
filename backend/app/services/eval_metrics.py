"""Pure metrics for guardrail effectiveness and confidence calibration.

Separate from the eval script so the math is importable and unit-tested. A "row"
is one evaluated receipt:

    {
      "expected_gate": "auto_post" | "review" | "reject" | None,  # ground truth
      "predicted_gate": "auto_post" | "review" | "reject",         # what the gate did
      "field_correct": bool,   # did every scored field read correctly?
      "confidence": float,     # the model's self-reported confidence
    }

The headline question these answer: *of the reads that were actually wrong, how
many did the gate wrongly auto-post?* (false_auto_post_rate — the dangerous miss)
and *of the reads that should have been held back, how many were?* (review_recall).
"""
from __future__ import annotations

from typing import Any

GATES = ("auto_post", "review", "reject")

# Default confidence buckets (lo inclusive, hi exclusive; last hi is 1.01 to catch 1.0).
DEFAULT_BUCKETS = [(0.0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def confusion_matrix(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """{expected: {predicted: count}} over the 3 gate classes. Only rows that carry
    an `expected_gate` ground-truth label are counted."""
    m = {e: {p: 0 for p in GATES} for e in GATES}
    for r in rows:
        exp, pred = r.get("expected_gate"), r.get("predicted_gate")
        if exp in GATES and pred in GATES:
            m[exp][pred] += 1
    return m


def routing_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How well the gate routes. The core metrics are OBJECTIVE — they compare the
    gate's decision against whether the read was actually correct (already ground-
    truthed by the field labels), so they need no extra hand-labelling:

    - false_auto_post_rate: of WRONG reads, the share that still auto-posted — the
      dangerous miss a guardrail exists to prevent. Lower is better.
    - guardrail_recall_on_wrong: the complement — wrong reads correctly held back.
    - over_review_rate: of CORRECT reads, the share sent to review anyway (friction,
      not danger). Lower is better.

    gate_accuracy is OPTIONAL: it needs an `expected_gate` ground-truth and is only
    computed over rows that carry one. All rates are None when their denom is 0.
    """
    wrong = [r for r in rows if r.get("field_correct") is False]
    correct = [r for r in rows if r.get("field_correct") is True]
    false_auto = [r for r in wrong if r.get("predicted_gate") == "auto_post"]
    over_reviewed = [r for r in correct if r.get("predicted_gate") != "auto_post"]

    labelled = [r for r in rows if r.get("expected_gate") in GATES]
    exact = [r for r in labelled if r.get("predicted_gate") == r["expected_gate"]]

    return {
        "n": len(rows),
        "wrong_reads": len(wrong),
        "false_auto_posts": len(false_auto),
        "false_auto_post_rate": _rate(len(false_auto), len(wrong)),
        "guardrail_recall_on_wrong": _rate(len(wrong) - len(false_auto), len(wrong)),
        "correct_reads": len(correct),
        "over_reviewed": len(over_reviewed),
        "over_review_rate": _rate(len(over_reviewed), len(correct)),
        "n_labelled": len(labelled),
        "gate_accuracy": _rate(len(exact), len(labelled)),
    }


def confidence_calibration(
    rows: list[dict[str, Any]], buckets: list[tuple[float, float]] | None = None
) -> list[dict[str, Any]]:
    """Per confidence-bucket: how often the read was actually correct. A well-
    calibrated model's accuracy rises with its confidence; a flat/inverted curve
    means the self-reported confidence can't be trusted as a gate signal."""
    buckets = buckets or DEFAULT_BUCKETS
    out: list[dict[str, Any]] = []
    for lo, hi in buckets:
        in_bucket = [
            r for r in rows
            if r.get("confidence") is not None and lo <= float(r["confidence"]) < hi
        ]
        correct = [r for r in in_bucket if r.get("field_correct")]
        out.append({
            "range": f"{lo:.1f}-{min(hi, 1.0):.1f}",
            "n": len(in_bucket),
            "accuracy": _rate(len(correct), len(in_bucket)),
        })
    return out
