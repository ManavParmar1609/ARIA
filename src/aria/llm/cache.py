"""Answers to repeated deterministic requests, kept in memory for a while.

A request at temperature 0 to the same provider and model, with the same messages, schema and
reply budget, deserves the same answer, and asking again would only spend the provider's limits.
Entries live for ``ttl_s`` seconds, at most ``max_entries`` of them (the oldest goes first),
under a SHA-256 of the request. Nothing about who asked is kept. Requests answered with a
visitor's own key never come here (the router keeps them out), so no visitor ever gets an answer
another visitor's key paid for.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from aria.config import ResponseCacheConfig
from aria.llm.base import Message, Usage


@dataclass(frozen=True)
class _Entry:
    expires: float
    text: str
    finish_reason: str | None


def cache_key(
    *,
    provider: str,
    model: str,
    endpoint: str | None,
    mode: str,
    messages: Sequence[Message],
    json_schema: dict[str, Any] | None,
    schema_name: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """A digest of everything that shapes the answer, and nothing about who asked."""
    request = {
        "provider": provider,
        "model": model,
        "endpoint": endpoint or "",
        "mode": mode,
        "messages": [[m.role, m.content] for m in messages],
        "schema": json_schema,
        "schema_name": schema_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    blob = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


class ResponseCache:
    def __init__(
        self, *, ttl_s: float, max_entries: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    @classmethod
    def from_config(
        cls, config: ResponseCacheConfig, *, clock: Callable[[], float] = time.monotonic
    ) -> ResponseCache:
        return cls(ttl_s=config.ttl_s, max_entries=config.max_entries, clock=clock)

    @property
    def enabled(self) -> bool:
        return self.ttl_s > 0 and self.max_entries > 0

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> tuple[str, Usage] | None:
        """The stored answer, with usage that says it cost nothing, or None."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires <= self._clock():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        usage = Usage(cost_usd=0.0, finish_reason=entry.finish_reason, cached=True)
        return entry.text, usage

    def put(self, key: str, text: str, usage: Usage) -> None:
        if not self.enabled or not text:
            return
        self._entries[key] = _Entry(self._clock() + self.ttl_s, text, usage.finish_reason)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
