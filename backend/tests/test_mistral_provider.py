"""The Mistral provider wiring, with no network. How well it reads is measured by the eval
matrix (eval/test/MODELS.md), not asserted here."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services import extraction
from app.services.llm_trace import LlmCall, price_usd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_extraction as ev  # noqa: E402

GOOD_JSON = '{"vendor": "Shop", "total": 5.0, "confidence": 0.9}'


def _settings(**overrides):
    return Settings(_env_file=None, llm_provider="mistral", mistral_api_key="test-key", **overrides)


def test_mistral_needs_its_own_key():
    assert _settings().llm_configured is True
    assert Settings(_env_file=None, llm_provider="mistral", mistral_api_key="", openai_api_key="x").llm_configured is False


def test_the_default_model_is_a_dated_name_so_a_matrix_row_cant_drift():
    assert "latest" not in Settings(_env_file=None).mistral_model


def test_the_price_comes_from_mistrals_list_and_other_models_keep_theirs():
    assert price_usd("mistral-small-2603", 1_000_000, 1_000_000) == 0.75
    assert price_usd("mistral-medium-3-5", 1_000_000, 1_000_000) == 0.0
    assert price_usd("gpt-5-mini", 1_000_000, 0) == 0.25


def test_extract_once_dispatches_mistral(monkeypatch):
    def fake(image_bytes, media_type, settings, prompt, kind="receipt_extract"):
        return {"confidence": 0.5}, LlmCall(provider="mistral", model=settings.mistral_model)

    monkeypatch.setattr(extraction, "_extract_mistral", fake)
    _, call = extraction._extract_once(b"x", "image/jpeg", "mistral", _settings(), "prompt")
    assert call.provider == "mistral"


def test_extract_receipt_routes_to_mistral_with_the_shared_prompt(monkeypatch):
    seen = {}

    def fake(image_bytes, media_type, settings, prompt, kind="receipt_extract"):
        seen["prompt"] = prompt
        return {"vendor": "Shop", "total": 5.0, "confidence": 0.9}, LlmCall(provider="mistral", model=settings.mistral_model)

    monkeypatch.setattr(extraction, "_extract_mistral", fake)
    result, _, trace = extraction.extract_receipt(b"not-an-image", "r.jpg", _settings())
    assert result.vendor == "Shop"
    assert (trace["provider"], trace["model"]) == ("mistral", "mistral-small-2603")
    assert seen["prompt"] == extraction._build_prompt()


def test_date_reread_works_on_mistral(monkeypatch):
    import datetime

    def fake(image_bytes, media_type, settings, prompt, kind="receipt_extract"):
        assert kind == "date_reread"
        return {"date": "2026-03-13"}, LlmCall(provider="mistral", model=settings.mistral_model)

    monkeypatch.setattr(extraction, "_extract_mistral", fake)
    assert extraction.reread_date(b"x", "r.jpg", _settings(), datetime.date(2026, 3, 20)) == datetime.date(2026, 3, 13)


class _FakeOpenAI:
    made: list[dict] = []
    sent: list[dict] = []

    def __init__(self, **kwargs):
        _FakeOpenAI.made.append(kwargs)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        _FakeOpenAI.sent.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=GOOD_JSON))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=100),
        )


@pytest.fixture
def fake_client(monkeypatch):
    import openai

    _FakeOpenAI.made, _FakeOpenAI.sent = [], []
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(extraction, "wrap_openai_if_enabled", lambda client: client)
    return _FakeOpenAI


def test_a_failed_structured_read_falls_back_and_says_so(monkeypatch, fake_client):
    import instructor

    def broken(*a, **k):
        raise RuntimeError("structured mode unavailable")

    monkeypatch.setattr(instructor, "from_openai", broken)
    payload, call = extraction._extract_mistral(b"img", "image/jpeg", _settings(), "the prompt")

    assert payload["vendor"] == "Shop"
    assert call.fell_back is True
    assert fake_client.made[0]["base_url"] == "https://api.mistral.ai/v1"
    assert fake_client.made[0]["api_key"] == "test-key"
    sent = fake_client.sent[0]
    assert sent["model"] == "mistral-small-2603"
    text, image = sent["messages"][0]["content"]
    assert text["text"] == "the prompt"
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert call.est_cost_usd == price_usd("mistral-small-2603", 1000, 100)


def test_a_structured_read_is_validated_in_json_mode(monkeypatch, fake_client):
    import instructor

    seen = {}

    def from_openai(client, mode=None):
        seen["mode"] = mode

        def create(**kwargs):
            seen["response_model"] = kwargs["response_model"]
            raw = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))
            return extraction.ExtractionResult(vendor="Shop", total=5.0, confidence=0.9), raw

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create_with_completion=create)))

    monkeypatch.setattr(instructor, "from_openai", from_openai)
    payload, call = extraction._extract_mistral(b"img", "image/jpeg", _settings(), "the prompt")

    assert seen["mode"] == instructor.Mode.JSON
    assert seen["response_model"] is extraction.ExtractionResult
    assert payload["vendor"] == "Shop"
    assert call.fell_back is False
    assert fake_client.sent == []


@pytest.mark.parametrize("provider, attribute", [
    ("mistral", "mistral_model"), ("anthropic", "anthropic_model"), ("ollama", "ollama_model"), ("openai", "openai_model"),
])
def test_the_eval_points_each_provider_at_the_named_model_and_keys_its_cache_on_it(provider, attribute):
    settings = Settings(_env_file=None, llm_provider=provider)
    ev._set_model(settings, "some-model")
    assert getattr(settings, attribute) == "some-model"
    assert ev._model_of(settings) == "some-model"
