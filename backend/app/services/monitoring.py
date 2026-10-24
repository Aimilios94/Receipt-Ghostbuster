"""Optional, opt-in Sentry error tracking — the app-layer complement to the LLM
observability (LangSmith / llm_traces) and the eval harness.

Mirrors the soft-dependency convention of services/llm_trace.py:
  1. gated on config read at call time (`settings.sentry_configured`),
  2. the third-party import is lazy + inside try/except, so a missing package or a
     failed init is a silent no-op (the app must import and run with no DSN),
  3. nothing here ever raises into the request path.

Privacy (see docs/MONITORING.md): initialised with `send_default_pii=False` and a
`before_send` scrubber that strips the request body, headers, cookies and query
string — so a receipt image, bank-statement text, IBAN/card number or auth token is
never shipped to Sentry's cloud. Performance tracing is off by default (sample rate
0.0): errors only.
"""
from __future__ import annotations

from typing import Any

_RELEASE = "receipt-ghostbuster@0.3.4"

# Request keys that can carry personal/financial data or secrets — dropped before send.
_SCRUB_REQUEST_KEYS = ("data", "headers", "cookies", "query_string")


def _scrub(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """before_send hook: remove anything that could carry receipt/bank/PII or a
    secret. We keep the exception + stack + our own safe tags; we drop the HTTP
    request payload entirely (we never need the body to triage a server error)."""
    req = event.get("request")
    if isinstance(req, dict):
        for key in _SCRUB_REQUEST_KEYS:
            req.pop(key, None)
    return event


def init_sentry_if_enabled(settings: Any) -> bool:
    """Initialise Sentry when a DSN is configured; otherwise a no-op. Returns whether
    Sentry was initialised (handy for /health and tests)."""
    if not getattr(settings, "sentry_configured", False):
        return False
    try:
        import sentry_sdk  # lazy: absence/init failure must not break the app
    except Exception:  # noqa: BLE001
        return False
    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            release=_RELEASE,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            send_default_pii=False,
            before_send=_scrub,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def capture(exc: BaseException, *, surface: str | None = None) -> None:
    """Report an exception to Sentry if it is initialised; a no-op otherwise. Used at
    the error surfaces the pipeline deliberately swallows (provider fallback, DB/n8n
    calls, import parsers) so those failures become visible without changing behaviour.
    Never raises."""
    try:
        import sentry_sdk

        if surface:
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("surface", surface)
                sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001 - monitoring must never break the request path
        pass


def capture_message(message: str, *, level: str = "info", surface: str | None = None) -> None:
    """Record a noteworthy non-exception event (e.g. a structured-output fallback) if
    Sentry is initialised; a no-op otherwise. Never raises."""
    try:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            if surface:
                scope.set_tag("surface", surface)
            sentry_sdk.capture_message(message, level=level)
    except Exception:  # noqa: BLE001
        pass
