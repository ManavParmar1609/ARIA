"""Long-lived objects the API shares across requests, and the dependencies that reach them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status

from aria.api.metrics import Metrics
from aria.api.security import KeyAuth, Principal, RateLimiter, principal_of
from aria.api.worker import Worker
from aria.graph.runner import TriageRunner
from aria.llm.allowance import SharedAllowance
from aria.services import Services


@dataclass
class AppState:
    services: Services
    runner: TriageRunner
    worker: Worker
    auth: KeyAuth
    limiter: RateLimiter
    metrics: Metrics
    allowance: SharedAllowance
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def inprocess(self) -> bool:
        return self.services.settings.worker_mode == "inprocess"


def app_state(request: Request) -> AppState:
    state = getattr(request.app.state, "aria", None)
    if state is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ARIA is starting up")
    return state  # type: ignore[no-any-return]


def current_principal(request: Request) -> Principal:
    return principal_of(request.state)
