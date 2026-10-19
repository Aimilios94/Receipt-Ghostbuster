"""Lightweight, self-contained observability for LLM calls.

Every provider call is timed and its token usage read from the SDK response, so
we can record latency, tokens and an estimated cost per read — the data the
"Model & Evals" dashboard shows. This module is DB-free: it produces a trace
record; the router persists it (keeping services DB-free, like the rest of the
app, so the eval harness can run the pipeline without a database).

LangSmith is an OPTIONAL extra: when `LANGSMITH_TRACING` is enabled and the
`langsmith` package is installed, the OpenAI/Anthropic clients are wrapped so
full traces (prompt, response, tokens) also flow to the user's LangSmith
project. When it's off or not installed, everything here still works unchanged.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

# Approximate public list prices (USD per 1M tokens) as (input, output). These
# give the dashboard a rough cost signal; they are estimates, not billing-exact,
# and prefix-matched so "gpt-5-mini-2025-..." still resolves.
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "o4-mini": (1.10, 4.40),
    "claude-opus-4-8": (15.00, 75.00),
    "claude-opus": (15.00, 75.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-haiku": (0.80, 4.00),
}


def price_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD cost of one call. 0.0 for an unknown model (never guesses)."""
    key = (model or "").lower()
    rate = next((v for k, v in _PRICING.items() if key.startswith(k)), None)
    if rate is None:
        return 0.0
    cin, cout = rate
    return round((input_tokens / 1_000_000) * cin + (output_tokens / 1_000_000) * cout, 6)


def usage_from(resp: Any) -> tuple[int, int]:
    """(input_tokens, output_tokens) from an OpenAI or Anthropic response.

    OpenAI exposes `prompt_tokens`/`completion_tokens`; Anthropic exposes
    `input_tokens`/`output_tokens`. Returns (0, 0) if usage is absent."""
    u = getattr(resp, "usage", None)
    if u is None:
        return (0, 0)
    inp = getattr(u, "input_tokens", None)
    if inp is None:
        inp = getattr(u, "prompt_tokens", 0)
    out = getattr(u, "output_tokens", None)
    if out is None:
        out = getattr(u, "completion_tokens", 0)
    return (int(inp or 0), int(out or 0))


@dataclass
class LlmCall:
    """One provider round-trip."""

    provider: str
    model: str
    kind: str = "receipt_extract"
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost_usd: float = 0.0
    success: bool = True
    error: str | None = None
    retries: int = 0
    fell_back: bool = False

    @classmethod
    def timed(
        cls,
        *,
        provider: str,
        model: str,
        kind: str,
        started: float,
        resp: Any = None,
        success: bool = True,
        error: str | None = None,
        retries: int = 0,
        fell_back: bool = False,
    ) -> "LlmCall":
        inp, out = usage_from(resp) if resp is not None else (0, 0)
        return cls(
            provider=provider,
            model=model,
            kind=kind,
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_tokens=inp,
            output_tokens=out,
            est_cost_usd=price_usd(model, inp, out),
            success=success,
            error=error,
            retries=retries,
            fell_back=fell_back,
        )


def aggregate(calls: list[LlmCall], *, provider: str, model: str, kind: str) -> dict[str, Any]:
    """Collapse the set of calls made for one logical operation (e.g. the several
    orientation reads of a single receipt) into one trace record for persistence."""
    return {
        "provider": provider,
        "model": model,
        "kind": kind,
        "latency_ms": sum(c.latency_ms for c in calls),
        "input_tokens": sum(c.input_tokens for c in calls),
        "output_tokens": sum(c.output_tokens for c in calls),
        "est_cost_usd": round(sum(c.est_cost_usd for c in calls), 6),
        "success": any(c.success for c in calls) if calls else False,
        "error": next((c.error for c in calls if c.error), None),
        "reads": len(calls),
        "retries": sum(c.retries for c in calls),
        "fell_back": any(c.fell_back for c in calls),
    }


# --------------------------------------------------------------------------- #
# Optional LangSmith client wrapping (opt-in, soft dependency)
# --------------------------------------------------------------------------- #
def langsmith_enabled() -> bool:
    return os.getenv("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes")


def wrap_openai_if_enabled(client: Any) -> Any:
    """Wrap an OpenAI client with LangSmith tracing when enabled; else unchanged."""
    if not langsmith_enabled():
        return client
    try:
        from langsmith.wrappers import wrap_openai  # type: ignore
    except Exception:  # noqa: BLE001 - langsmith not installed → no-op
        return client
    return wrap_openai(client)


def wrap_anthropic_if_enabled(client: Any) -> Any:
    """Wrap an Anthropic client with LangSmith tracing when enabled; else unchanged."""
    if not langsmith_enabled():
        return client
    try:
        from langsmith.wrappers import wrap_anthropic  # type: ignore
    except Exception:  # noqa: BLE001
        return client
    return wrap_anthropic(client)
