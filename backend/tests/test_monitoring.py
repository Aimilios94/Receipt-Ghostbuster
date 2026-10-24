"""Opt-in Sentry wiring (services/monitoring.py). Mirrors the env-gated no-op pattern
of test_llm_trace.py: everything is asserted with sentry_sdk.init monkeypatched, so no
DSN is contacted and no network call is made."""
import sentry_sdk

from app.config import Settings
from app.services import monitoring


def test_sentry_configured_reflects_dsn():
    assert Settings(sentry_dsn="").sentry_configured is False
    assert Settings(sentry_dsn="https://fake@example.com/1").sentry_configured is True


def test_init_is_noop_without_dsn(monkeypatch):
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    assert monitoring.init_sentry_if_enabled(Settings(sentry_dsn="")) is False
    assert calls == []  # init must not be called when there is no DSN


def test_init_called_once_with_privacy_defaults(monkeypatch):
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    settings = Settings(sentry_dsn="https://fake@example.com/1",
                        sentry_environment="test", sentry_traces_sample_rate=0.0)
    assert monitoring.init_sentry_if_enabled(settings) is True
    assert len(calls) == 1
    kw = calls[0]
    assert kw["dsn"] == "https://fake@example.com/1"
    assert kw["environment"] == "test"
    assert kw["send_default_pii"] is False        # no PII ever
    assert kw["traces_sample_rate"] == 0.0        # errors only
    assert callable(kw["before_send"])            # scrubber wired


def test_init_returns_false_if_sdk_raises(monkeypatch):
    def boom(**kw):
        raise RuntimeError("bad dsn")
    monkeypatch.setattr(sentry_sdk, "init", boom)
    # A failed init must be swallowed (the app still runs), reported as not-enabled.
    assert monitoring.init_sentry_if_enabled(Settings(sentry_dsn="https://fake@example.com/1")) is False


def test_before_send_scrubs_request_payload():
    event = {
        "exception": {"values": [{"type": "ValueError"}]},
        "request": {
            "url": "http://localhost:8000/extract",
            "method": "POST",
            "data": b"...receipt image bytes...",
            "headers": {"Authorization": "Bearer secret-token"},
            "cookies": "session=abc",
            "query_string": "token=leak",
        },
    }
    out = monitoring._scrub(event, {})
    req = out["request"]
    # URL/method kept (safe, useful); body / headers / cookies / query dropped.
    assert req["url"].endswith("/extract") and req["method"] == "POST"
    for leaked in ("data", "headers", "cookies", "query_string"):
        assert leaked not in req
    # The exception itself is preserved.
    assert out["exception"]["values"][0]["type"] == "ValueError"


def test_before_send_tolerates_no_request():
    event = {"exception": {"values": []}}
    assert monitoring._scrub(event, {}) is event  # unchanged, no error


def test_capture_calls_capture_exception(monkeypatch):
    seen = []
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda e: seen.append(e))
    err = ValueError("x")
    monitoring.capture(err)
    assert seen == [err]


def test_capture_with_surface_sets_tag_and_reports(monkeypatch):
    seen = []
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda e: seen.append(e))
    err = RuntimeError("y")
    monitoring.capture(err, surface="extract.upload_receipt")
    assert seen == [err]


def test_capture_never_raises(monkeypatch):
    def boom(_e):
        raise RuntimeError("sentry down")
    monkeypatch.setattr(sentry_sdk, "capture_exception", boom)
    # Must be a silent no-op — monitoring may never break the request path.
    monitoring.capture(ValueError("x"))
    monitoring.capture(ValueError("x"), surface="s")


def test_capture_message_never_raises(monkeypatch):
    def boom(_m, level=None):
        raise RuntimeError("sentry down")
    monkeypatch.setattr(sentry_sdk, "capture_message", boom)
    monitoring.capture_message("hello", level="warning", surface="s")
