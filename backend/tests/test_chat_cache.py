"""Chatbot response cache (v0.5 Slice 3) — pure, offline. The cache key includes a
ledger fingerprint, so a repeated question hits the cache but any data change misses
(self-invalidation). The answer_question integration is driven by a stub client, so
no API is called."""
from app.services import chat_cache, chat as chat_service


def _ledger(amount=20.0):
    return {
        "expenses": [{"expense_date": "2026-10-05", "amount": amount, "category": "Groceries",
                      "vendor": "Continente", "status": "posted"}],
        "bank": [], "subscriptions": [], "line_items": {},
    }


# --- fingerprint + key ------------------------------------------------------ #
def test_fingerprint_is_stable_and_order_independent():
    a = _ledger()
    b = {"line_items": {}, "subscriptions": [], "bank": [],
         "expenses": [{"vendor": "Continente", "status": "posted", "category": "Groceries",
                       "amount": 20.0, "expense_date": "2026-10-05"}]}
    assert chat_cache.ledger_fingerprint(a) == chat_cache.ledger_fingerprint(b)


def test_fingerprint_changes_when_data_changes():
    assert chat_cache.ledger_fingerprint(_ledger(20.0)) != chat_cache.ledger_fingerprint(_ledger(21.0))


def test_cache_key_depends_on_question_model_scope_and_ledger():
    base = chat_cache.cache_key("How much?", _ledger(), "gpt-5-mini", "user1")
    assert base == chat_cache.cache_key("  how   much?  ", _ledger(), "gpt-5-mini", "user1")  # normalised
    assert base != chat_cache.cache_key("How much?", _ledger(), "gpt-5-mini", "user2")  # scope
    assert base != chat_cache.cache_key("How much?", _ledger(21.0), "gpt-5-mini", "user1")  # data
    assert base != chat_cache.cache_key("How much?", _ledger(), "gpt-4o", "user1")  # model


def test_lru_evicts_oldest():
    c = chat_cache.ResponseCache(maxsize=2)
    c.set("a", {"v": 1}); c.set("b", {"v": 2})
    c.get("a")              # touch a so b is now oldest
    c.set("c", {"v": 3})    # evicts b
    assert c.get("a") and c.get("c") and c.get("b") is None


# --- answer_question integration (stub client, offline) --------------------- #
class _FakeFn:
    def __init__(self, name, arguments):
        self.name, self.arguments = name, arguments


class _FakeToolCall:
    def __init__(self, name, arguments):
        self.id, self.type, self.function = "c1", "function", _FakeFn(name, arguments)


class _Msg:
    def __init__(self, content, tool_calls=None):
        self.content, self.tool_calls = content, tool_calls


class _Resp:
    def __init__(self, message):
        self.choices = [type("C", (), {"message": message})()]


class _CountingCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1 or (self.calls % 2) == 1:
            return _Resp(_Msg("", [_FakeToolCall("total_spend", '{"month": "2026-10"}')]))
        return _Resp(_Msg("You spent €20.00 in October."))


class _StubClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _CountingCompletions()})()


class _Settings:
    openai_model = "gpt-5-mini"
    openai_api_key = "unused"


def test_answer_question_caches_repeat_and_invalidates_on_change():
    chat_cache.clear()
    data = _ledger()
    client = _StubClient()
    settings = _Settings()
    r1 = chat_service.answer_question("How much did I spend in October?", [], data, settings,
                                      client=client, use_cache=True, cache_scope="user1")
    first_calls = client.chat.completions.calls
    assert first_calls >= 1 and "20.00" in r1["answer"]

    # identical question, unchanged ledger -> cache hit, no new model calls
    r2 = chat_service.answer_question("How much did I spend in October?", [], data, settings,
                                      client=client, use_cache=True, cache_scope="user1")
    assert r2.get("cached") is True
    assert client.chat.completions.calls == first_calls  # no extra calls

    # ledger changed -> fingerprint differs -> cache miss -> model called again
    chat_service.answer_question("How much did I spend in October?", [], _ledger(21.0), settings,
                                 client=client, use_cache=True, cache_scope="user1")
    assert client.chat.completions.calls > first_calls


def test_answer_question_does_not_cache_with_history_or_when_disabled():
    chat_cache.clear()
    data = _ledger()
    # history present -> never cached
    chat_service.answer_question("q", [{"role": "user", "content": "earlier"}], data, _Settings(),
                                 client=_StubClient(), use_cache=True, cache_scope="u")
    assert chat_cache.get_cached("q", data, "gpt-5-mini", "u") is None
    # use_cache False -> never cached
    chat_service.answer_question("q2", [], data, _Settings(),
                                 client=_StubClient(), use_cache=False, cache_scope="u")
    assert chat_cache.get_cached("q2", data, "gpt-5-mini", "u") is None
