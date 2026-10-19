"""LLM observability helpers: pricing, usage extraction, aggregation, LangSmith
soft-wrapping. Pure — no network."""
import os
from types import SimpleNamespace

from app.services import llm_trace
from app.services.llm_trace import LlmCall, aggregate, price_usd, usage_from


def test_price_usd_prefix_matches_model():
    # gpt-5-mini: $0.25/1M in, $2.00/1M out
    assert price_usd("gpt-5-mini", 1_000_000, 1_000_000) == round(0.25 + 2.00, 6)
    # prefix match works for a dated variant
    assert price_usd("gpt-5-mini-2026-01-01", 1_000_000, 0) == 0.25
    # unknown model never guesses
    assert price_usd("some-unknown-model", 1_000_000, 1_000_000) == 0.0


def test_usage_from_openai_and_anthropic_shapes():
    openai_resp = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=40))
    assert usage_from(openai_resp) == (100, 40)
    anthropic_resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=200, output_tokens=55))
    assert usage_from(anthropic_resp) == (200, 55)
    assert usage_from(SimpleNamespace()) == (0, 0)  # no usage attr
    assert usage_from(None) == (0, 0)


def test_aggregate_sums_calls():
    calls = [
        LlmCall(provider="openai", model="gpt-5-mini", latency_ms=1000, input_tokens=100,
                output_tokens=40, est_cost_usd=0.001, success=True),
        LlmCall(provider="openai", model="gpt-5-mini", latency_ms=500, input_tokens=50,
                output_tokens=20, est_cost_usd=0.0005, success=True, fell_back=True),
    ]
    agg = aggregate(calls, provider="openai", model="gpt-5-mini", kind="receipt_extract")
    assert agg["latency_ms"] == 1500
    assert agg["input_tokens"] == 150
    assert agg["output_tokens"] == 60
    assert agg["est_cost_usd"] == 0.0015
    assert agg["reads"] == 2
    assert agg["fell_back"] is True
    assert agg["success"] is True


def test_aggregate_empty_is_not_success():
    agg = aggregate([], provider="mock", model="mock", kind="receipt_extract")
    assert agg["reads"] == 0
    assert agg["success"] is False


def test_langsmith_wrap_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    assert llm_trace.langsmith_enabled() is False
    sentinel = object()
    # With tracing off, the client is returned unchanged (no langsmith dependency hit).
    assert llm_trace.wrap_openai_if_enabled(sentinel) is sentinel
    assert llm_trace.wrap_anthropic_if_enabled(sentinel) is sentinel
