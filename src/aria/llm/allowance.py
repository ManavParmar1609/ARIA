"""The site's own model keys, shared with visitors who bring none, within a daily allowance.

A public demo can carry its owner's provider key so that every visitor sees a model at work. Left
open, one visitor could spend it all. The allowance counts model-written runs and answers per
visitor and for the whole site, per UTC day: past either limit, the work runs offline (rules, the
calibrated model and the grounded template), which still works end to end. A visitor's own key
never counts against it.

Counts live in this process's memory, so a restart starts the day afresh, and replicas count apart:
set ``per_day`` with that in mind. A visitor is their private session (the console's
``X-Visitor-Id``), not their address: behind the web server every visitor arrives from the same one.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from aria.config import SharedAllowanceConfig


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


@dataclass(frozen=True)
class Allowance:
    """What a visitor may still use today: None means no limit."""

    left: int | None
    per_visitor: int | None
    per_day: int | None


class SharedAllowance:
    """Per-visitor and per-site daily counts of work the site's own keys do."""

    def __init__(self, config: SharedAllowanceConfig, *, today: Callable[[], str] = _today) -> None:
        self.per_visitor = config.per_visitor or None
        self.per_day = config.per_day or None
        self._today = today
        self._lock = threading.Lock()
        self._day = ""
        self._site = 0
        self._visitors: dict[str, int] = {}

    @property
    def limited(self) -> bool:
        return self.per_visitor is not None or self.per_day is not None

    def _roll(self) -> None:
        day = self._today()
        if day != self._day:
            self._day, self._site, self._visitors = day, 0, {}

    def check(self, visitor: str) -> Allowance:
        """How much this visitor may still use today, without using any of it."""
        with self._lock:
            self._roll()
            left = [
                limit - used
                for limit, used in (
                    (self.per_visitor, self._visitors.get(visitor, 0)),
                    (self.per_day, self._site),
                )
                if limit is not None
            ]
            return Allowance(max(0, min(left)) if left else None, self.per_visitor, self.per_day)

    def take(self, visitor: str) -> bool:
        """Count one piece of model work for this visitor, if today's allowance has room."""
        with self._lock:
            self._roll()
            mine = self._visitors.get(visitor, 0)
            if self.per_visitor is not None and mine >= self.per_visitor:
                return False
            if self.per_day is not None and self._site >= self.per_day:
                return False
            self._visitors[visitor] = mine + 1
            self._site += 1
            return True
