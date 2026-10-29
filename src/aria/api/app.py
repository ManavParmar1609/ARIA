"""The ARIA API: REST and SSE for runs, plus MCP, A2A and AG-UI endpoints on one server.

``uvicorn aria.api.app:app`` (or ``aria serve``). One process serves:

* ``/api/v1/...``: runs (with server-sent events), reviews, forks, alerts, Ask ARIA, catalog;
* ``/mcp``: ARIA's read-only MCP tools over streamable HTTP (stateless);
* ``/a2a`` and ``/.well-known/agent-card.json``: the A2A agent;
* ``/agui``: the AG-UI agent endpoint for CopilotKit-style frontends;
* ``/healthz``, ``/readyz``, ``/metrics``; and the web dashboard when ``ARIA_WEB_DIST_DIR`` is set.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from a2a.server.routes import add_a2a_routes_to_fastapi
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aria import __version__
from aria.api.a2a import a2a_routes
from aria.api.agui import router as agui_router
from aria.api.jobs import start_background_jobs
from aria.api.metrics import Metrics
from aria.api.routers import catalog, intake, runs, system
from aria.api.security import AuthMiddleware, KeyAuth, RateLimiter
from aria.api.state import AppState
from aria.api.worker import Worker
from aria.config import Settings, get_settings, load_dotenv_file
from aria.graph.runner import RunBusyError, RunNotFoundError, RunStateError, TriageRunner
from aria.mcp.server import build_server
from aria.observability.logging import configure_logging, get_logger
from aria.observability.tracing import configure_tracing
from aria.services import Services

log = get_logger(__name__)
_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
]


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *_SECURITY_HEADERS]
            await send(message)

        await self.app(scope, receive, with_headers)


def _allowed_hosts(settings: Settings) -> list[str]:
    hosts = ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    public = urlsplit(settings.public_base_url).netloc
    if public:
        hosts += [public, f"{public.split(':')[0]}:*"]
    return hosts


def create_app(
    *,
    settings: Settings | None = None,
    services: Services | None = None,
    runner: TriageRunner | None = None,
) -> FastAPI:
    """Build the app. Tests pass ``services``/``runner``; otherwise they start with the app."""
    load_dotenv_file()
    settings = settings or (services.settings if services else get_settings())
    raw_keys = settings.api_keys.get_secret_value() if settings.api_keys else None
    auth = KeyAuth(raw_keys)
    if settings.is_prod and auth.open:
        msg = "ARIA_API_KEYS must be set in production"
        raise RuntimeError(msg)
    limiter = RateLimiter(settings.rate_limit_per_minute)
    holder: dict[str, AppState] = {}

    def current() -> AppState:
        if "state" not in holder:
            msg = "ARIA is starting up"
            raise RuntimeError(msg)
        return holder["state"]

    mcp = build_server(provider=lambda: current().services)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=_allowed_hosts(settings),
            allowed_origins=[*settings.cors_origins, settings.public_base_url.rstrip("/")],
        ),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, settings.log_format)
        configure_tracing(settings.otel_exporter, endpoint=settings.otlp_endpoint)
        if settings.migrate_on_start and services is None:
            from aria.db.migrate import upgrade  # noqa: PLC0415 - Alembic only when asked

            await asyncio.to_thread(upgrade, "head", settings.database_url)
            log.info("api.migrated")
        owned = services is None
        svc = services or await Services.create(settings=settings)
        run = runner or TriageRunner(svc)
        metrics = Metrics(svc.engine)
        run.observers.append(metrics.observe)
        worker = Worker(run, concurrency=settings.worker_concurrency)
        state = AppState(svc, run, worker, auth, limiter, metrics)
        holder["state"] = state
        app.state.aria = state
        if auth.open:
            log.warning("api.open", hint="set ARIA_API_KEYS to require API keys")
        stop = asyncio.Event()
        background: list[asyncio.Task[None]] = []
        async with mcp.session_manager.run():
            if state.inprocess:
                await worker.recover()
                background.extend(start_background_jobs(svc, run, stop, on_run=worker.execute))
            log.info("api.started", version=__version__, worker=settings.worker_mode)
            try:
                yield
            finally:
                stop.set()
                await asyncio.gather(*background, return_exceptions=True)
                await worker.drain()
                holder.pop("state", None)
                if owned:
                    await svc.aclose()

    app = FastAPI(
        title="ARIA",
        version=__version__,
        description="First-pass incident triage with auditable agents.",
        lifespan=lifespan,
    )
    app.add_middleware(AuthMiddleware, auth=auth, limiter=limiter)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "authorization",
            "content-type",
            "x-api-key",
            "last-event-id",
            "a2a-version",
        ],
        expose_headers=["retry-after"],
    )
    app.add_middleware(SecurityHeaders)

    for module in (system, runs, catalog, intake):
        app.include_router(module.router)
    app.include_router(agui_router)
    app.router.routes.extend(mcp_app.routes)
    card_routes, rpc_routes = a2a_routes(lambda: current().runner, settings, secured=not auth.open)
    add_a2a_routes_to_fastapi(app, agent_card_routes=card_routes, jsonrpc_routes=rpc_routes)

    @app.exception_handler(RunNotFoundError)
    async def not_found(_: Request, exc: RunNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": f"run {exc.args[0] if exc.args else ''} not found"}, 404)

    @app.exception_handler(RunStateError)
    async def conflict(_: Request, exc: RunStateError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, 409)

    @app.exception_handler(RunBusyError)
    async def busy(_: Request, exc: RunBusyError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, 409)

    if settings.web_dist_dir and Path(settings.web_dist_dir).is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dist_dir, html=True), name="web")
    return app


def __getattr__(name: str) -> FastAPI:
    """``aria.api.app:app`` builds the app on first use, so importing this module is cheap."""
    if name == "app":
        built = create_app()
        globals()["app"] = built
        return built
    raise AttributeError(name)
