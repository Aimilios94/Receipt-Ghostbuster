"""Newer Claude models use the API's own structured output; older ones keep Instructor. And a
cost is tokens times a price that matches the provider's list, so saved reads follow a correction."""
import datetime
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services import extraction
from app.services.llm_trace import price_usd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_extraction as ev  # noqa: E402

GOOD_JSON = '{"vendor": "Shop", "total": 5.0, "confidence": 0.9}'
USAGE = SimpleNamespace(input_tokens=1000, output_tokens=100)


def _settings(model):
    return Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key="test-key", anthropic_model=model)


@pytest.mark.parametrize("model, expected", [
    ("gpt-5-mini", (0.25, 2.00)),
    ("gpt-4o", (2.50, 10.00)),
    ("gpt-5.6-terra", (2.00, 12.00)),
    ("mistral-small-2603", (0.15, 0.60)),
    ("claude-opus-4-8", (5.00, 25.00)),
    ("claude-sonnet-5-5", (2.00, 10.00)),
    ("claude-haiku-5-5", (0.10, 0.50)),
    ("claude-haiku-4-5", (1.00, 5.00)),
    ("claude-haiku-4-5-20251001", (1.00, 5.00)),
])
def test_prices_match_each_providers_list(model, expected):
    assert price_usd(model, 1_000_000, 0) == expected[0]
    assert price_usd(model, 0, 1_000_000) == expected[1]


@pytest.mark.parametrize("model", ["claude-sonnet-9-9", "claude-haiku-9", "claude-opus-9"])
def test_an_unlisted_model_costs_nothing_rather_than_a_guessed_family_price(model):
    assert price_usd(model, 1_000_000, 1_000_000) == 0.0


@pytest.mark.parametrize("model, thinks", [
    ("claude-sonnet-5-5", True),
    ("claude-haiku-5-5", True),
    ("claude-opus-5-5", True),
    ("claude-fable-5-1", True),
    ("claude-opus-4-8", False),
    ("claude-haiku-4-5", False),
    ("claude-sonnet-4-6", False),
])
def test_which_models_use_the_new_path(model, thinks):
    assert extraction._anthropic_thinks_by_default(model) is thinks


class _FakeMessages:
    def __init__(self, parse_result=None, parse_error=None):
        self.parse_result, self.parse_error = parse_result, parse_error
        self.parse_calls: list[dict] = []
        self.create_calls: list[dict] = []

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        if self.parse_error:
            raise self.parse_error
        return self.parse_result

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        thinking = SimpleNamespace(type="thinking", thinking="")
        return SimpleNamespace(content=[thinking, SimpleNamespace(type="text", text=GOOD_JSON)], usage=USAGE)


@pytest.fixture
def client(monkeypatch):
    import anthropic

    holder = SimpleNamespace(messages=_FakeMessages())
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: holder)
    monkeypatch.setattr(extraction, "wrap_anthropic_if_enabled", lambda c: c)
    return holder


def _parsed(obj, stop_reason="end_turn"):
    return SimpleNamespace(parsed_output=obj, stop_reason=stop_reason, usage=USAGE)


def test_a_new_model_uses_structured_output_with_room_for_thinking(monkeypatch, client):
    import instructor

    def must_not_run(*a, **k):
        raise AssertionError("Instructor's forced tool call is rejected by these models")

    monkeypatch.setattr(instructor, "from_anthropic", must_not_run)
    client.messages.parse_result = _parsed(extraction.ExtractionResult(vendor="Shop", total=5.0, confidence=0.9))
    payload, call = extraction._extract_anthropic(b"img", "image/jpeg", _settings("claude-sonnet-5-5"), "the prompt")

    assert payload["vendor"] == "Shop"
    assert call.fell_back is False
    assert call.est_cost_usd == price_usd("claude-sonnet-5-5", 1000, 100)
    sent = client.messages.parse_calls[0]
    assert sent["output_format"] is extraction.ExtractionResult
    assert sent["max_tokens"] == 16000
    assert "thinking" not in sent and "temperature" not in sent
    assert "fallbacks" not in sent
    image, text = sent["messages"][0]["content"]
    assert image["source"]["media_type"] == "image/jpeg"
    assert text["text"] == "the prompt"


@pytest.mark.parametrize("failure", [
    {"parse_error": RuntimeError("schema rejected")},
    {"parse_result": _parsed(None, stop_reason="refusal")},
])
def test_a_failed_structured_read_falls_back_and_reads_only_the_text(client, failure):
    client.messages = _FakeMessages(**failure)
    payload, call = extraction._extract_anthropic(b"img", "image/jpeg", _settings("claude-haiku-5-5"), "the prompt")

    assert payload["vendor"] == "Shop"
    assert call.fell_back is True
    assert client.messages.create_calls[0]["max_tokens"] == 16000


def test_an_older_model_keeps_its_exact_path(monkeypatch, client):
    import instructor

    seen = {}

    def from_anthropic(c):
        def create(**kwargs):
            seen.update(kwargs)
            return extraction.ExtractionResult(vendor="Shop", confidence=0.9), SimpleNamespace(usage=USAGE)

        return SimpleNamespace(messages=SimpleNamespace(create_with_completion=create))

    monkeypatch.setattr(instructor, "from_anthropic", from_anthropic)
    payload, call = extraction._extract_anthropic(b"img", "image/jpeg", _settings("claude-opus-4-8"), "the prompt")

    assert payload["vendor"] == "Shop"
    assert seen["max_tokens"] == 4096
    assert seen["response_model"] is extraction.ExtractionResult
    assert client.messages.parse_calls == []


def _saved_read(tmp_path, monkeypatch, trace):
    monkeypatch.setattr(ev, "CACHE_DIR", tmp_path)
    (tmp_path / "a.anthropic.claude-opus-4-8.models.json").write_text(
        json.dumps({"result": {"vendor": "Shop", "confidence": 0.9}, "trace": trace}), encoding="utf-8"
    )
    return ev.read_receipt(tmp_path / "a.jpg", _settings("claude-opus-4-8"), datetime.date(2026, 11, 6), use_cache=True)[1]


def test_a_saved_read_is_costed_at_todays_price_from_its_recorded_tokens(tmp_path, monkeypatch):
    trace = _saved_read(tmp_path, monkeypatch, {
        "model": "claude-opus-4-8", "input_tokens": 17171, "output_tokens": 834, "est_cost_usd": 0.3201,
    })
    assert trace["est_cost_usd"] == price_usd("claude-opus-4-8", 17171, 834)
    assert trace["input_tokens"] == 17171


def test_a_saved_read_with_no_recorded_tokens_keeps_its_cost(tmp_path, monkeypatch):
    trace = _saved_read(tmp_path, monkeypatch, {"model": "claude-opus-4-8", "est_cost_usd": 0.0})
    assert trace["est_cost_usd"] == 0.0


def test_only_gpt_5_6_uses_json_mode_so_other_openai_reads_are_unchanged():
    import instructor

    assert extraction._openai_structured_kwargs("gpt-5.6-terra") == {"mode": instructor.Mode.JSON}
    assert extraction._openai_structured_kwargs("gpt-5-mini") == {}
    assert extraction._openai_structured_kwargs("gpt-4o") == {}
