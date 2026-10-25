"""Chatbot eval harness (v0.5 Slice 2) — the scoring is pure and unit-tested, and
the offline --check over the committed synthetic ledger must stay 100% (that is the
deterministic CI gate). No API is called here. A stub OpenAI client drives the real
tool-calling loop offline so answer_question's loop is covered too."""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

import eval_chatbot as ec  # noqa: E402
from app.services import chat as chat_service  # noqa: E402


# --------------------------------------------------------------------------- #
# deep_subset
# --------------------------------------------------------------------------- #
def test_deep_subset_scalars_and_money_tolerance():
    assert ec.deep_subset(10.0, 10.004)          # within €0.01
    assert not ec.deep_subset(10.0, 10.5)
    assert ec.deep_subset("Groceries", "Groceries")
    assert not ec.deep_subset("Groceries", "groceries")  # string match is exact


def test_deep_subset_bool_is_not_a_number():
    # True == 1 in Python; deep_subset must not treat a bool as a numeric match.
    assert not ec.deep_subset(True, 1)
    assert ec.deep_subset(True, True)


def test_deep_subset_dict_is_partial():
    actual = {"total": 138.99, "count": 6, "extra": "ignored"}
    assert ec.deep_subset({"total": 138.99}, actual)
    assert not ec.deep_subset({"count": 5}, actual)
    assert not ec.deep_subset({"missing": 1}, actual)


def test_deep_subset_list_is_membership_unordered():
    actual = [{"vendor": "Pingo Doce", "amount": 50.0}, {"vendor": "Continente", "amount": 30.0}]
    assert ec.deep_subset([{"vendor": "Continente"}], actual)        # order-free
    assert ec.deep_subset([{"vendor": "Pingo Doce", "amount": 50.0}], actual)
    assert not ec.deep_subset([{"vendor": "Lidl"}], actual)


# --------------------------------------------------------------------------- #
# args_match / tool_call_matches
# --------------------------------------------------------------------------- #
def test_args_match_subset_and_case_insensitive():
    assert ec.args_match({"month": "2026-10"}, {"month": "2026-10"})
    assert ec.args_match({"category": "Groceries"}, {"category": "groceries"})  # normalised
    assert ec.args_match({}, {"month": "2026-10"})               # label pins nothing extra
    assert not ec.args_match({"month": "2026-10"}, {"month": "2026-09"})
    assert not ec.args_match({"month": "2026-10"}, {})           # required arg missing


def test_tool_call_matches_single_and_alternatives():
    used = [{"name": "spend_by_day", "args": {"month": "2026-10"}}]
    assert ec.tool_call_matches({"name": "spend_by_day", "args": {"month": "2026-10"}}, used)
    assert not ec.tool_call_matches({"name": "total_spend", "args": {"month": "2026-10"}}, used)
    # a list of acceptable alternatives: any one matching is a pass
    alts = [{"name": "get_receipt", "args": {"vendor": "Pingo Doce"}},
            {"name": "get_receipt", "args": {"date": "2026-10-20", "vendor": "Pingo Doce"}}]
    assert ec.tool_call_matches(alts, [{"name": "get_receipt", "args": {"vendor": "Pingo Doce"}}])


def test_refusal_ok_means_no_tool_called():
    assert ec.refusal_ok([])
    assert not ec.refusal_ok([{"name": "total_spend", "args": {"month": "2026-10"}}])


# --------------------------------------------------------------------------- #
# offline grading over the committed fixture
# --------------------------------------------------------------------------- #
def _load():
    ledger = json.loads((ec.EVAL_DIR / "ledger.json").read_text(encoding="utf-8"))
    qdoc = json.loads((ec.EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
    return ledger, qdoc


def test_offline_check_is_100pct_over_committed_fixture():
    """The deterministic CI gate: every answerable question's expected tool, dispatched
    over the committed ledger, must yield its expected answer. If this drifts, the
    analytics surface or a label changed — exactly what the mock baseline guards."""
    ledger, qdoc = _load()
    answerable = [q for q in qdoc["questions"] if q["kind"] == "answerable"]
    assert answerable, "fixture should have answerable questions"
    for q in answerable:
        ok, result = ec.answer_offline(q, ledger)
        assert ok, f"{q['id']} expected {q['expected_answer']} got {result}"


def test_every_expected_tool_name_is_a_real_tool():
    _, qdoc = _load()
    valid = {t["function"]["name"] for t in chat_service.TOOLS}
    for q in qdoc["questions"]:
        if q["kind"] != "answerable":
            continue
        specs = q["expected_tool"] if isinstance(q["expected_tool"], list) else [q["expected_tool"]]
        for s in specs:
            assert s["name"] in valid, f"{q['id']} references unknown tool {s['name']}"


# --------------------------------------------------------------------------- #
# the tool-calling loop, driven offline by a stub client
# --------------------------------------------------------------------------- #
class _FakeFn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, name, arguments):
        self.id = "call_1"
        self.type = "function"
        self.function = _FakeFn(name, arguments)


class _FakeMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeResp:
    def __init__(self, message):
        self.choices = [type("C", (), {"message": message})()]


class _FakeCompletions:
    """First call -> ask for a tool; second call -> a final natural answer."""
    def __init__(self):
        self._n = 0

    def create(self, **kwargs):
        self._n += 1
        if self._n == 1:
            return _FakeResp(_FakeMessage("", [_FakeToolCall("total_spend", '{"month": "2026-10"}')]))
        return _FakeResp(_FakeMessage("You spent €138.99 in October."))


class _FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _FakeCompletions()})()


class _Settings:
    openai_model = "gpt-5-mini"
    openai_api_key = "unused"


def test_answer_question_loop_with_injected_client():
    ledger, _ = _load()
    res = chat_service.answer_question(
        "How much did I spend in October?", [], ledger, _Settings(), client=_FakeClient()
    )
    assert res["grounded"] is True
    assert res["used_tools"] == [{"name": "total_spend", "args": {"month": "2026-10"}}]
    assert "138.99" in res["answer"]
