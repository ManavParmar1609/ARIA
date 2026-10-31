"""Visitors' own model keys: checked as they arrive, held in memory for the work they came with.

A key arrives with one request (the ``X-Model-Provider`` and ``X-Model-Key`` headers). A run's
request is stored and replayed, so the key never joins it: the API holds the key here under the
run's id until the runner starts that run, takes it into the run's own router and closes the
router when the run stops. Nothing here is written anywhere. A restart forgets every key, and a
run whose key is gone carries on with this server's own providers.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import SecretStr

# Anthropic, Google, OpenAI and NVIDIA keys are runs of [A-Za-z0-9_-] today. This is looser, so a
# new format still works, and strict enough that only a token, never a line break, reaches a
# header.
_KEY = re.compile(r"[A-Za-z0-9._-]{20,200}")
HOLD_S = 30 * 60  # how long a key waits for its run to start
MAX_HELD = 1_000


@dataclass(frozen=True)
class VisitorKey:
    """A visitor's key and the kind of key it is (``claude``, ``gemini``, ...). Printing it shows
    the kind only."""

    provider: str
    key: SecretStr


def parse_key(value: str) -> SecretStr | None:
    """The key in ``value``, or None if it does not look like an API key."""
    value = value.strip()
    return SecretStr(value) if _KEY.fullmatch(value) else None


class VisitorKeys:
    """Keys waiting for the runs they came with to start, each for at most ``hold_s`` seconds."""

    def __init__(
        self,
        *,
        hold_s: float = HOLD_S,
        limit: int = MAX_HELD,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.hold_s = hold_s
        self.limit = limit
        self._clock = clock
        self._held: OrderedDict[str, tuple[float, VisitorKey]] = OrderedDict()

    def __len__(self) -> int:
        self._expire()
        return len(self._held)

    def hold(self, run_id: str, key: VisitorKey) -> None:
        self._expire()
        self._held[run_id] = (self._clock() + self.hold_s, key)
        self._held.move_to_end(run_id)
        while len(self._held) > self.limit:  # the oldest run then starts with this server's keys
            self._held.popitem(last=False)

    def take(self, run_id: str) -> VisitorKey | None:
        """The run's key, which is no longer held here once taken."""
        self._expire()
        held = self._held.pop(run_id, None)
        return held[1] if held else None

    def drop(self, run_id: str) -> None:
        self._held.pop(run_id, None)

    def _expire(self) -> None:
        now = self._clock()
        while self._held:
            until, _ = next(iter(self._held.values()))
            if until > now:
                break
            self._held.popitem(last=False)
