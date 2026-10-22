"""The local Ollama provider wiring — config + dispatch, without a live server.

Ollama runs on-device (the privacy-first option), so there's no key and no network
in CI. These tests prove the provider is configured without a key and that the
shipped `extract_receipt` pipeline routes an `ollama` read to `_extract_ollama`
against the configured local model, recording a $0-cost trace. The actual quality
of a local read is measured by the eval harness (eval/MODELS.md), not asserted here.
"""
from app.config import Settings
from app.services import extraction
from app.services.llm_trace import LlmCall


def test_ollama_configured_without_api_key():
    # Local provider needs no API key — only Ollama running + a model pulled.
    s = Settings(llm_provider="ollama", openai_api_key="", anthropic_api_key="")
    assert s.llm_configured is True
    # Sanity: the cloud providers still require their key.
    assert Settings(llm_provider="openai", openai_api_key="").llm_configured is False


def test_extract_receipt_routes_to_ollama(monkeypatch):
    s = Settings(llm_provider="ollama", ollama_model="qwen2.5vl:7b")
    seen: dict[str, object] = {}

    def fake_ollama(image_bytes, media_type, settings, prompt, kind="receipt_extract"):
        seen["model"] = settings.ollama_model
        seen["base_url"] = settings.ollama_base_url
        payload = {
            "vendor": "Continente",
            "date": "2026-10-06",
            "total": 4.14,
            "vat_amount": 0.57,
            "vat_rate": 13,
            "currency": "EUR",
            "line_items": [],
            "tax_lines": [],
            "confidence": 0.9,
        }
        # Local model -> price_usd returns 0 for an unknown model, so cost is $0.
        return payload, LlmCall(provider="ollama", model=settings.ollama_model)

    monkeypatch.setattr(extraction, "_extract_ollama", fake_ollama)

    result, oriented, trace = extraction.extract_receipt(b"\xff\xd8\xff not-a-real-jpeg", "r.jpg", s)

    assert seen["model"] == "qwen2.5vl:7b"
    assert seen["base_url"] == "http://localhost:11434/v1"
    assert result.vendor == "Continente"
    assert result.total == 4.14
    assert trace["provider"] == "ollama"
    assert trace["model"] == "qwen2.5vl:7b"
    assert trace["est_cost_usd"] == 0.0  # local reads are free


def test_extract_once_dispatches_ollama(monkeypatch):
    s = Settings(llm_provider="ollama")
    called = {"n": 0}

    def fake_ollama(image_bytes, media_type, settings, prompt, kind="receipt_extract"):
        called["n"] += 1
        return {"confidence": 0.5}, LlmCall(provider="ollama", model=settings.ollama_model)

    monkeypatch.setattr(extraction, "_extract_ollama", fake_ollama)
    payload, call = extraction._extract_once(b"x", "image/jpeg", "ollama", s, "prompt")
    assert called["n"] == 1
    assert call.provider == "ollama"
