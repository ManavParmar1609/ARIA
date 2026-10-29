"""API authentication and rate limiting, applied to every protected path by one ASGI middleware.

Keys come from ``ARIA_API_KEYS``: a comma-separated list of ``name:secret`` pairs (a bare secret
is named ``api``). Clients send ``Authorization: Bearer <secret>`` or ``X-API-Key: <secret>``.
Secrets are compared in constant time and never logged. With no keys configured the API is open
in dev and test; ``create_app`` refuses to start that way in prod.

The middleware also covers the mounted MCP, A2A and AG-UI endpoints, which FastAPI dependencies
would not reach. Rate limiting is a per-principal token bucket (per client address when the API
is open), kept in memory: right for a single instance; several instances need a shared limiter
or a gateway in front.
"""

from __future__ import annotations

import hmac
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

PUBLIC_PATHS = frozenset(
    {"/healthz", "/readyz", "/.well-known/agent-card.json", "/docs", "/openapi.json", "/redoc"}
)
PROTECTED_PREFIXES = ("/api/", "/mcp", "/a2a", "/agui", "/metrics")


@dataclass(frozen=True)
class Principal:
    name: str
    authenticated: bool


def parse_keys(raw: str | None) -> dict[str, str]:
    """``name:secret,secret2`` → ``{secret: name}``. Empty entries are ignored."""
    keys: dict[str, str] = {}
    for raw_entry in (raw or "").split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        name, sep, secret = entry.partition(":")
        if not sep:
            name, secret = "api", entry
        if secret:
            keys[secret.strip()] = name.strip() or "api"
    return keys


class KeyAuth:
    def __init__(self, raw_keys: str | None) -> None:
        self._keys = parse_keys(raw_keys)

    @property
    def open(self) -> bool:
        return not self._keys

    def authenticate(self, headers: dict[str, str]) -> Principal | None:
        if self.open:
            return Principal("anonymous", authenticated=False)
        token = headers.get("x-api-key", "")
        auth = headers.get("authorization", "")
        if not token and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if not token:
            return None
        for secret, name in self._keys.items():
            if hmac.compare_digest(secret.encode(), token.encode()):
                return Principal(name, authenticated=True)
        return None


class RateLimiter:
    """A token bucket per key: ``per_minute`` requests a minute, bursting up to the same."""

    def __init__(self, per_minute: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str) -> tuple[bool, float]:
        """Whether the request may go ahead, and if not, seconds until it could."""
        now = self.clock()
        tokens, last = self._buckets.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens >= 1:
            self._buckets[key] = (tokens - 1, now)
            return True, 0.0
        self._buckets[key] = (tokens, now)
        return False, (1 - tokens) / self.rate

    def prune(self, idle_s: float = 3_600) -> None:
        cutoff = self.clock() - idle_s
        for key in [k for k, (_, last) in self._buckets.items() if last < cutoff]:
            del self._buckets[key]


def is_protected(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return False
    return path.startswith(PROTECTED_PREFIXES)


class AuthMiddleware:
    """Authenticates and rate-limits protected paths; sets ``request.state.principal``."""

    def __init__(self, app: ASGIApp, *, auth: KeyAuth, limiter: RateLimiter) -> None:
        self.app = app
        self.auth = auth
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_protected(scope["path"]):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        principal = self.auth.authenticate(headers)
        if principal is None:
            await _reject(send, 401, "missing or invalid API key", {"www-authenticate": "Bearer"})
            return
        client = scope.get("client") or ("unknown", 0)
        bucket = principal.name if principal.authenticated else f"ip:{client[0]}"
        allowed, retry_after = self.limiter.allow(bucket)
        if not allowed:
            await _reject(
                send, 429, "rate limit exceeded", {"retry-after": str(math.ceil(retry_after))}
            )
            return
        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)


async def _reject(send: Send, status: int, detail: str, headers: dict[str, str]) -> None:
    body = json.dumps({"detail": detail}).encode()
    raw: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        *((k.encode(), v.encode()) for k, v in headers.items()),
    ]
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": body})


def principal_of(state: Any) -> Principal:
    principal = getattr(state, "principal", None)
    return principal if isinstance(principal, Principal) else Principal("anonymous", False)
