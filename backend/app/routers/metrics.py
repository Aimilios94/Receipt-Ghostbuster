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

_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
_METRICS_JSON = _EVAL_DIR / "metrics.json"
_CHAT_METRICS_JSON = _EVAL_DIR / "chatbot" / "metrics.json"
_CHAT_QUESTIONS_JSON = _EVAL_DIR / "chatbot" / "questions.json"
_CHAT_DETAIL_JSON = _EVAL_DIR / "chatbot" / "results.detail.json"


def _read_metrics(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"available": False}
    return {"available": True, **data}


@router.get("/eval")
def eval_metrics(user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    """The offline extraction-accuracy + guardrail eval aggregates (committed file)."""
    return _read_metrics(_METRICS_JSON)


@router.get("/eval/chat")
def chat_eval_metrics(user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    """The Ask chatbot's eval aggregates (committed file)."""
    return _read_metrics(_CHAT_METRICS_JSON)


def merge_chat_questions(questions: list[dict[str, Any]], detail: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each eval question with its result from the last live run. A question that run didn't
    cover has no result, shown as not run rather than as a pass or a fail."""
    by_id = {d.get("id"): d for d in detail}
    merged = []
    for q in questions:
        d = by_id.get(q.get("id"))
        merged.append({
            "id": q.get("id"),
            "kind": q.get("kind"),
            "question": q.get("question"),
            "ran": d is not None,
            "tool_selection": (d or {}).get("tool_ok"),
            "answer_correctness": (d or {}).get("answer_ok"),
            "refusal": (d or {}).get("refusal_ok"),
            "faithfulness": (d or {}).get("faithful"),
            "tools": [t.get("name") for t in (d or {}).get("used_tools") or []],
        })
    return merged


@router.get("/eval/chat/questions")
def chat_eval_questions(user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    """The eval's questions with pass or fail. They run against a synthetic ledger, so they
    hold no personal data. The per-question results exist only where the eval was run."""
    try:
        questions = json.loads(_CHAT_QUESTIONS_JSON.read_text(encoding="utf-8"))["questions"]
    except Exception:  # noqa: BLE001
        return {"available": False, "questions": []}
    try:
        detail = json.loads(_CHAT_DETAIL_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        detail = []
    return {"available": True, "questions": merge_chat_questions(questions, detail)}


def _pctl(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def summarize_traces(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate traces of one kind. For Ask, cached and failed questions are counted but
    left out of latency and cost: a cache hit takes no time, and a failure produced no answer."""
    n = len(traces)
    if n == 0:
        return {"total_reads": 0, "recent": []}

    def is_measured(t: dict[str, Any]) -> bool:
        if t.get("kind") != "chat":
            return True
        return t.get("success") is not False and not (t.get("meta") or {}).get("cached")

    measured = [t for t in traces if is_measured(t)]
    measured_n = len(measured)
    cached = sum(1 for t in traces if (t.get("meta") or {}).get("cached"))
    failed = sum(1 for t in traces if t.get("kind") == "chat" and t.get("success") is False)
    traces, all_traces = measured, traces
    lat = sorted(float(t.get("latency_ms") or 0) for t in traces)
    tot_cost = round(sum(float(t.get("est_cost_usd") or 0) for t in traces), 6)
    in_tok = sum(int(t.get("input_tokens") or 0) for t in traces)
    out_tok = sum(int(t.get("output_tokens") or 0) for t in traces)

    by_outcome: dict[str, int] = {}
    by_model: dict[str, dict[str, Any]] = {}
    fell_back = 0
    for t in all_traces:
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
            "tools": (t.get("meta") or {}).get("tools") or [],
            "cached": bool((t.get("meta") or {}).get("cached")),
        }
        for t in all_traces[:25]
    ]

    return {
        "total_reads": n,
        "cached": cached,
        "failed": failed,
        "latency_ms": {"p50": _pctl(lat, 50), "p95": _pctl(lat, 95),
                       "avg": round(sum(lat) / measured_n) if measured_n else 0},
        "cost_usd": {"total": tot_cost, "avg": round(tot_cost / measured_n, 6) if measured_n else 0},
        "tokens": {"input": in_tok, "output": out_tok, "total": in_tok + out_tok},
        "fell_back": fell_back,
        "by_outcome": by_outcome,
        "by_model": by_model,
        "recent": recent,
    }


@router.get("/llm")
def llm_metrics(
    kind: str = "reads",
    limit: int = 500,
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Live observability from this user's recorded calls: receipt reads by default, or
    `kind=chat` for Ask, so the two very different workloads aren't averaged together."""
    want_chat = kind == "chat"
    traces = repo.list_llm_traces(user_id, limit=limit)
    return summarize_traces([t for t in traces if (t.get("kind") == "chat") == want_chat])
