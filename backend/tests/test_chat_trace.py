"""Ask's cost and latency tracking, and months with no records in a comparison."""
from types import SimpleNamespace

import pytest

from app.routers.metrics import summarize_traces
from app.services import analytics, chat, chat_cache
from app.services.llm_trace import price_usd

DATA = {
    "expenses": [{"id": "e1", "expense_date": "2026-10-03", "amount": 20.0, "vendor": "Shop",
                  "category": "Groceries", "source": "card"}],
    "bank": [], "subscriptions": [], "line_items": {},
}
SECRET_QUESTION = "how much did my friend Robin owe me in October"


def _response(content="Done", tool_calls=None, tokens=(1000, 500)):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=tokens[0], completion_tokens=tokens[1])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _tool_call(name, arguments):
    return SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=arguments))


class _Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        next_item = self.responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


SETTINGS = SimpleNamespace(openai_model="gpt-5-mini", openai_api_key="unused")


def _ask(client, **kwargs):
    traces = []
    result = chat.answer_question(SECRET_QUESTION, [], DATA, SETTINGS, client=client,
                                  on_trace=traces.append, **kwargs)
    return result, traces


def test_trace_sums_every_model_call_for_one_question():
    client = _Client(
        _response(content="", tool_calls=[_tool_call("total_spend", '{"month": "2026-10"}')]),
        _response(content="You spent €20.00."),
    )
    _, [trace] = _ask(client)
    assert trace["kind"] == "chat" and trace["model"] == "gpt-5-mini"
    assert trace["input_tokens"] == 2000 and trace["output_tokens"] == 1000
    assert trace["est_cost_usd"] == price_usd("gpt-5-mini", 2000, 1000)
    assert trace["reads"] == 2
    assert trace["tools"] == ["total_spend"]
    assert trace["success"] is True and trace["cached"] is False
    assert trace["latency_ms"] >= 0


def test_trace_never_contains_the_question():
    _, [trace] = _ask(_Client(_response()))
    assert "Robin" not in str(trace)


def test_cached_answer_costs_nothing_and_is_marked():
    chat_cache.clear()
    _ask(_Client(_response()), use_cache=True, cache_scope="u")
    result, [trace] = _ask(_Client(), use_cache=True, cache_scope="u")
    assert result["cached"] is True
    assert trace["cached"] is True and trace["success"] is True
    assert trace["input_tokens"] == 0 and trace["est_cost_usd"] == 0
    chat_cache.clear()


def test_failure_is_traced_and_still_raised():
    traces = []
    with pytest.raises(RuntimeError):
        chat.answer_question(SECRET_QUESTION, [], DATA, SETTINGS, client=_Client(RuntimeError("no credits")),
                             on_trace=traces.append)
    assert traces[0]["success"] is False and "no credits" in traces[0]["error"]


def test_no_trace_callback_is_fine():
    result = chat.answer_question("hello", [], DATA, SETTINGS, client=_Client(_response()))
    assert result["answer"] == "Done" and "trace" not in result


def _trace(kind="chat", latency=1000, cost=0.01, success=True, **meta):
    return {"kind": kind, "model": "gpt-5-mini", "latency_ms": latency, "input_tokens": 10, "output_tokens": 5,
            "est_cost_usd": cost, "success": success, "meta": meta}


def test_summary_leaves_cached_and_failed_questions_out_of_latency_and_cost():
    summary = summarize_traces([
        _trace(latency=4000, cost=0.02, tools=["spend_by_day"]),
        _trace(latency=2000, cost=0.04, tools=["total_spend"]),
        _trace(latency=1, cost=0.0, cached=True, tools=["total_spend"]),
        _trace(latency=50, cost=0.0, success=False),
    ])
    assert summary["total_reads"] == 4 and summary["cached"] == 1 and summary["failed"] == 1
    assert summary["latency_ms"]["avg"] == 3000
    assert summary["cost_usd"]["total"] == 0.06 and summary["cost_usd"]["avg"] == 0.03
    assert summary["recent"][0]["tools"] == ["spend_by_day"]
    assert summary["recent"][2]["cached"] is True


def test_summary_with_only_cached_questions_does_not_divide_by_zero():
    summary = summarize_traces([_trace(cached=True)])
    assert summary["latency_ms"]["avg"] == 0 and summary["cost_usd"]["avg"] == 0


def test_summary_keeps_every_receipt_read_in_its_figures():
    summary = summarize_traces([_trace(kind="receipt_extract", latency=3000, cost=0.01, success=False)])
    assert summary["latency_ms"]["avg"] == 3000 and summary["cost_usd"]["total"] == 0.01
    assert summary["failed"] == 0


def test_comparing_with_a_month_with_no_records_has_no_delta():
    r = analytics.compare_category(DATA["expenses"], "Groceries", "2026-10", "2026-09")
    assert r["total_a"] == 20.0 and r["month_a_has_data"] is True
    assert r["month_b_has_data"] is False and r["delta"] is None and r["pct_change"] is None
    [card] = chat._attachments_for("compare_category", r, DATA, {})
    assert card["a"]["total"] == 20.0 and card["b"]["total"] is None and card["delta"] is None


def test_a_month_with_other_spending_really_is_zero_for_that_category():
    expenses = DATA["expenses"] + [{"id": "e2", "expense_date": "2026-09-05", "amount": 7.0, "vendor": "Cafe",
                                    "category": "Dining & Cafes", "source": "card"}]
    r = analytics.compare_category(expenses, "Groceries", "2026-10", "2026-09")
    assert r["total_b"] == 0 and r["month_b_has_data"] is True and r["delta"] == 20.0


def test_eval_questions_show_pass_fail_and_not_run():
    from app.routers.metrics import merge_chat_questions

    questions = [
        {"id": "q1", "kind": "answerable", "question": "A?"},
        {"id": "r1", "kind": "refusal", "question": "B?"},
        {"id": "q2", "kind": "answerable", "question": "C?"},
    ]
    detail = [
        {"id": "q1", "tool_ok": True, "answer_ok": False, "faithful": True,
         "used_tools": [{"name": "total_spend", "args": {}}]},
        {"id": "r1", "refusal_ok": True, "used_tools": []},
    ]
    q1, r1, q2 = merge_chat_questions(questions, detail)
    assert q1["tool_selection"] is True and q1["answer_correctness"] is False and q1["tools"] == ["total_spend"]
    assert r1["refusal"] is True and r1["ran"] is True
    assert q2["ran"] is False and q2["tool_selection"] is None
