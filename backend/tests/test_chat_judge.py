"""Faithfulness judge (v0.5 Slice 3) — the prompt builder + the tolerant verdict
parse are pure/offline; the judge call itself is driven by a stub client so no API
is used. A reply we can't parse must fail SAFE (unfaithful)."""
from app.services import chat_judge


def test_build_messages_includes_question_answer_and_tool_results():
    msgs = chat_judge.build_messages(
        "How much in October?",
        "You spent €20.00.",
        [{"month": "2026-10", "total": 20.0}],
    )
    assert msgs[0]["role"] == "system" and "faithfulness" in msgs[0]["content"].lower()
    user = msgs[1]["content"]
    assert "How much in October?" in user and "You spent €20.00." in user and "20.0" in user


def test_parse_verdict_faithful_and_unfaithful():
    assert chat_judge.parse_verdict('{"verdict": "faithful", "reason": "all figures match"}')["verdict"] == "faithful"
    assert chat_judge.parse_verdict('{"verdict":"unfaithful","reason":"invented €99"}')["verdict"] == "unfaithful"


def test_parse_verdict_extracts_embedded_json():
    out = chat_judge.parse_verdict('Sure:\n{"verdict": "faithful", "reason": "ok"}\nthanks')
    assert out["verdict"] == "faithful"


def test_parse_verdict_fails_safe_on_garbage():
    # unparseable / missing verdict -> treated as unfaithful, never silently faithful
    assert chat_judge.parse_verdict("totally not json")["verdict"] == "unfaithful"
    assert chat_judge.parse_verdict('{"reason": "no verdict key"}')["verdict"] == "unfaithful"
    assert chat_judge.parse_verdict("")["verdict"] == "unfaithful"


# --- the judge call, driven offline by a stub client ------------------------ #
class _Msg:
    def __init__(self, content):
        self.content = content


class _Resp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": _Msg(content)})()]


class _Completions:
    def __init__(self, reply):
        self._reply = reply
        self.seen_kwargs = None

    def create(self, **kwargs):
        self.seen_kwargs = kwargs
        return _Resp(self._reply)


class _Client:
    def __init__(self, reply):
        self.chat = type("Chat", (), {"completions": _Completions(reply)})()


class _Settings:
    openai_model = "gpt-5-mini"
    openai_api_key = "unused"


def test_judge_faithfulness_with_stub_client():
    client = _Client('{"verdict": "unfaithful", "reason": "answer says €99, tool says €20"}')
    out = chat_judge.judge_faithfulness(
        "How much?", "You spent €99.", [{"total": 20.0}], _Settings(), client=client
    )
    assert out["verdict"] == "unfaithful" and "99" in out["reason"]
    # gpt-5* must use max_completion_tokens (not max_tokens/temperature)
    assert "max_completion_tokens" in client.chat.completions.seen_kwargs
