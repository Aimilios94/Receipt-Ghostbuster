"""In-process response cache for the chatbot (v0.5 Slice 3).

A repeated question over an UNCHANGED ledger recomputes nothing — the whole model
round-trip (latency + tokens) is skipped. The cache key includes a fingerprint of
the user's ledger data, so it **self-invalidates** the moment any expense / bank
row / subscription changes: a stale answer is impossible by construction.

This is a deliberately simple, process-global cache (an OrderedDict LRU) — right for
a single-instance app. A multi-instance deployment would swap this for Redis keyed on
the same fingerprint; the key scheme is the part that matters and it carries over.

Pure + DB-free (like the rest of services/), so it is unit-testable without a server.
"""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any

MAX_ENTRIES = 256


def ledger_fingerprint(data: dict[str, Any]) -> str:
    """A short, stable hash of the ledger data bundle ({expenses, bank, subscriptions,
    line_items}). Canonical JSON (sorted keys) → sha1[:12], so the SAME data always
    fingerprints the same and ANY change (a new expense, an edited amount) changes it,
    invalidating the cached answers that depended on it."""
    blob = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:12]


def cache_key(message: str, data: dict[str, Any], model: str, scope: str = "") -> str:
    """Key one cached answer on (normalised question, ledger fingerprint, model, scope).
    `scope` is the user id — belt-and-braces, since the per-user data bundle already
    makes the fingerprint user-specific."""
    norm = " ".join((message or "").lower().split())
    raw = f"{scope}\x1f{model}\x1f{ledger_fingerprint(data)}\x1f{norm}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class ResponseCache:
    """A tiny bounded LRU over answer dicts. get() refreshes recency; set() evicts the
    least-recently-used entry past MAX_ENTRIES."""

    def __init__(self, maxsize: int = MAX_ENTRIES) -> None:
        self._store: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> dict[str, Any] | None:
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# Process-global instance used by the chat service. Resets on restart (acceptable for
# a single-instance app; the fingerprint keying is what guarantees correctness).
_CACHE = ResponseCache()


def get_cached(message: str, data: dict[str, Any], model: str, scope: str = "") -> dict[str, Any] | None:
    return _CACHE.get(cache_key(message, data, model, scope))


def put_cached(message: str, data: dict[str, Any], model: str, value: dict[str, Any], scope: str = "") -> None:
    _CACHE.set(cache_key(message, data, model, scope), value)


def clear() -> None:
    """Drop all cached answers (used by tests; also handy after a bulk data change)."""
    _CACHE.clear()
