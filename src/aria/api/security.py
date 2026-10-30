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

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aria.observability.logging import get_logger

access_log = get_logger("aria.api.access")

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

    def short_keys(self, minimum: int) -> list[str]:
        """Names of keys whose secret is shorter than ``minimum`` characters (never the secret)."""
        return sorted({name for secret, name in self._keys.items() if len(secret) < minimum})

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
    """A token bucket per key: ``per_minute`` requests a minute, bursting up to the same.

    Past ``max_buckets`` callers it forgets the ones idle long enough to have refilled, which
    changes no answer, at most once per refill time, so many addresses cannot grow it unbounded.
    """

    def __init__(
        self,
        per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_buckets: int = 10_000,
    ) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.clock = clock
        self.max_buckets = max_buckets
        self._buckets: dict[str, tuple[float, float]] = {}
        self._pruned_at = clock()

    def allow(self, key: str) -> tuple[bool, float]:
        """Whether the request may go ahead, and if not, seconds until it could."""
        now = self.clock()
        refill_s = self.capacity / self.rate
        if len(self._buckets) >= self.max_buckets and now - self._pruned_at >= refill_s:
            self.prune(idle_s=refill_s)
            self._pruned_at = now
        tokens, last = self._buckets.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens >= 1:
            self._buckets[key] = (tokens - 1, now)
            return True, 0.0
        self._buckets[key] = (tokens, now)
        return False, (1 - tokens) / self.rate

    def prune(self, idle_s: float = 3_600) -> None:
        """Forget callers idle for ``idle_s``; past the refill time a bucket is full anyway."""
        cutoff = self.clock() - idle_s
        for key in [k for k, (_, last) in self._buckets.items() if last < cutoff]:
            del self._buckets[key]


class BodyTooLargeError(HTTPException):
    """A request body without a declared length grew past the limit while being read.

    An HTTP error, so the app's own exception handling answers 413 (FastAPI turns any other
    exception raised while it reads a body into a 400).
    """

    def __init__(self, limit: int) -> None:
        super().__init__(413, f"request body larger than {limit} bytes")


class BodyLimit:
    """Refuses request bodies over ``max_bytes`` with 413 before the app holds them in memory."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        detail = f"request body larger than {self.max_bytes} bytes"
        declared = next((v for k, v in scope["headers"] if k.lower() == b"content-length"), None)
        if declared is not None:
            try:
                too_big = int(declared) > self.max_bytes
            except ValueError:
                too_big = True
            if too_big:
                await _reject(send, 413, detail, {})
                return
            await self.app(scope, receive, send)
            return
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLargeError(self.max_bytes)
            return message

        try:
            await self.app(scope, counted, send)
        except BodyTooLargeError:  # an app without its own HTTP error handling
            await _reject(send, 413, detail, {})


def is_protected(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return False
    return path.startswith(PROTECTED_PREFIXES)


def route_path(scope: Scope) -> str:
    """The path routing matches: behind a proxy prefix (an ASGI ``root_path`` such as
    ``/aria``), the request path without it, so ``/aria/api/v1/runs`` is checked as the
    protected ``/api/v1/runs`` it is served as."""
    path: str = scope["path"]
    root: str = scope.get("root_path") or ""
    if root and path.startswith(root) and path[len(root) : len(root) + 1] in ("", "/"):
        return path[len(root) :] or "/"
    return path


class AuthMiddleware:
    """Authenticates and rate-limits protected paths; sets ``request.state.principal``.

    Every request to a protected path leaves one access-log line (``api.request``): method,
    path, status, the key's name and the time taken, so who read or deleted what can be traced.
    The query string is left out, since callers sometimes put secrets there.
    """

    def __init__(self, app: ASGIApp, *, auth: KeyAuth, limiter: RateLimiter) -> None:
        self.app = app
        self.auth = auth
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = route_path(scope) if scope["type"] == "http" else ""
        if scope["type"] != "http" or not is_protected(path):
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        status: list[int] = [500]

        async def recorded(message: Message) -> None:
            if message["type"] == "http.response.start":
                status[0] = int(message["status"])
            await send(message)

        principal = self.auth.authenticate(
            {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        )
        try:
            await self._handle(scope, receive, recorded, principal)
        finally:
            access_log.info(
                "api.request",
                method=scope.get("method"),
                path=path,
                status=status[0],
                principal=principal.name if principal else None,
                ms=round((time.monotonic() - started) * 1_000, 1),
            )

    async def _handle(
        self, scope: Scope, receive: Receive, send: Send, principal: Principal | None
    ) -> None:
        client = scope.get("client") or ("unknown", 0)
        if principal is None:
            # Failed attempts spend the caller's address bucket, so keys cannot be guessed fast.
            allowed, retry_after = self.limiter.allow(f"ip:{client[0]}")
            if not allowed:
                await _reject(
                    send, 429, "rate limit exceeded", {"retry-after": str(math.ceil(retry_after))}
                )
                return
            await _reject(send, 401, "missing or invalid API key", {"www-authenticate": "Bearer"})
            return
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
