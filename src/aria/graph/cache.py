"""The graph's node cache, kept inside a fixed memory budget.

LangGraph's own ``InMemoryCache`` keeps an entry until the same key is read after it expires. A
shard's key includes its run, so that read never comes, and every large paste stayed in the API's
memory. This cache drops expired entries as it goes, and the oldest ones once it is full.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langgraph.cache.base import BaseCache, FullKey, Namespace

DEFAULT_MAX_BYTES = 16 * 1024 * 1024


class BoundedCache(BaseCache[Any]):
    """An in-memory node cache holding at most ``max_bytes`` of encoded values."""

    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__()
        self.max_bytes = max_bytes
        self.clock = clock
        self._entries: OrderedDict[FullKey, tuple[str, bytes, float | None]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    @property
    def size(self) -> int:
        """Bytes of encoded values held now."""
        return self._bytes

    def get(self, keys: Sequence[FullKey]) -> dict[FullKey, Any]:
        with self._lock:
            now = self.clock()
            found: dict[FullKey, Any] = {}
            for key in keys:
                entry = self._entries.get(key)
                if entry is None:
                    continue
                encoding, value, expiry = entry
                if expiry is not None and now >= expiry:
                    self._drop(key)
                    continue
                self._entries.move_to_end(key)
                found[key] = self.serde.loads_typed((encoding, value))
            return found

    async def aget(self, keys: Sequence[FullKey]) -> dict[FullKey, Any]:
        return self.get(keys)

    def set(self, pairs: Mapping[FullKey, tuple[Any, int | None]]) -> None:
        with self._lock:
            now = self.clock()
            for key, (value, ttl) in pairs.items():
                encoding, data = self.serde.dumps_typed(value)
                self._drop(key)
                if len(data) > self.max_bytes:
                    continue  # one value larger than the whole budget is not kept at all
                self._entries[key] = (encoding, data, None if ttl is None else now + ttl)
                self._bytes += len(data)
            for key in [
                k for k, (_, _, end) in self._entries.items() if end is not None and now >= end
            ]:
                self._drop(key)
            while self._bytes > self.max_bytes:
                self._drop(next(iter(self._entries)))

    async def aset(self, pairs: Mapping[FullKey, tuple[Any, int | None]]) -> None:
        self.set(pairs)

    def clear(self, namespaces: Sequence[Namespace] | None = None) -> None:
        with self._lock:
            if namespaces is None:
                self._entries.clear()
                self._bytes = 0
                return
            wanted = {tuple(ns) for ns in namespaces}
            for key in [k for k in self._entries if tuple(k[0]) in wanted]:
                self._drop(key)

    async def aclear(self, namespaces: Sequence[Namespace] | None = None) -> None:
        self.clear(namespaces)

    def _drop(self, key: FullKey) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= len(entry[1])
