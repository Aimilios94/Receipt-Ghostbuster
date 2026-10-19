"""Model & Evals metrics endpoints.

Two sources:
  * GET /metrics/eval — the committed, offline eval aggregates (accuracy, guardrail
    effectiveness, confidence calibration) produced by scripts/eval_extraction.py.
  * GET /metrics/llm  — LIVE operational telemetry aggregated from the llm_traces
    table (this user's reads): latency, tokens, estimated cost, and gate outcomes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import get_current_user_id
from .. import repository as repo

router = APIRouter(prefix="/metrics", tags=["metrics"])

_METRICS_JSON = Path(__file__).resolve().parents[2] / "eval" / "metrics.json"


@router.get("/eval")
def eval_metrics(user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    """The offline extraction-accuracy + guardrail eval aggregates (committed file)."""
    if not _METRICS_JSON.exists():
        return {"available": False}
    try:
        data = json.loads(_METRICS_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"available": False}
    return {"available": True, **data}


def _pctl(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


@router.get("/llm")
def llm_metrics(
    limit: int = 500,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Live observability aggregated from this user's recorded LLM calls."""
    traces = repo.list_llm_traces(user_id, limit=limit)
    n = len(traces)
    if n == 0:
        return {"total_reads": 0, "recent": []}

    lat = sorted(float(t.get("latency_ms") or 0) for t in traces)
    tot_cost = round(sum(float(t.get("est_cost_usd") or 0) for t in traces), 6)
    in_tok = sum(int(t.get("input_tokens") or 0) for t in traces)
    out_tok = sum(int(t.get("output_tokens") or 0) for t in traces)

    by_outcome: dict[str, int] = {}
    by_model: dict[str, dict[str, Any]] = {}
    fell_back = 0
    for t in traces:
        meta = t.get("meta") or {}
        outcome = meta.get("gated_to") or "—"
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        if meta.get("fell_back"):
            fell_back += 1
        m = t.get("model") or "—"
        bm = by_model.setdefault(m, {"reads": 0, "latency_sum": 0, "cost": 0.0})
        bm["reads"] += 1
        bm["latency_sum"] += int(t.get("latency_ms") or 0)
        bm["cost"] = round(bm["cost"] + float(t.get("est_cost_usd") or 0), 6)
    for m, bm in by_model.items():
        bm["avg_latency_ms"] = round(bm["latency_sum"] / bm["reads"]) if bm["reads"] else 0
        del bm["latency_sum"]

    recent = [
        {
            "created_at": t.get("created_at"),
            "kind": t.get("kind"),
            "provider": t.get("provider"),
            "model": t.get("model"),
            "latency_ms": t.get("latency_ms"),
            "input_tokens": t.get("input_tokens"),
            "output_tokens": t.get("output_tokens"),
            "est_cost_usd": t.get("est_cost_usd"),
            "success": t.get("success"),
            "gated_to": (t.get("meta") or {}).get("gated_to"),
            "source": (t.get("meta") or {}).get("source"),
            "fell_back": (t.get("meta") or {}).get("fell_back", False),
            "guardrails_fired": (t.get("meta") or {}).get("guardrails_fired") or [],
        }
        for t in traces[:25]
    ]

    return {
        "total_reads": n,
        "latency_ms": {"p50": _pctl(lat, 50), "p95": _pctl(lat, 95), "avg": round(sum(lat) / n)},
        "cost_usd": {"total": tot_cost, "avg": round(tot_cost / n, 6)},
        "tokens": {"input": in_tok, "output": out_tok, "total": in_tok + out_tok},
        "fell_back": fell_back,
        "by_outcome": by_outcome,
        "by_model": by_model,
        "recent": recent,
    }
