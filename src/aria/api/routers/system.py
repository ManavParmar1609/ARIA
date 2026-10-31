"""Liveness, readiness, metrics and LLM provider status."""

from __future__ import annotations

import asyncio
import math
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import text

from aria import __version__
from aria.api.keys import VisitorKeyDep, accepted_kinds
from aria.api.metrics import CONTENT_TYPE
from aria.api.schemas import Health, Me, ModelKeyCheck, ProviderOut, SettingsOut
from aria.api.security import Principal
from aria.api.state import AppState, app_state, current_principal
from aria.db.engine import session_scope
from aria.llm.base import Message, ProviderError
from aria.notify import channel_env

router = APIRouter(tags=["system"])
State = Annotated[AppState, Depends(app_state)]
Caller = Annotated[Principal, Depends(current_principal)]


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is serving requests."""
    return {"status": "ok", "version": __version__}


def _database_ok(state: AppState) -> bool:
    try:
        with session_scope(state.services.engine) as session:
            session.execute(text("SELECT 1"))
    except Exception:  # readiness reports any failure as not ready
        return False
    return True


@router.get("/readyz", response_model=Health)
async def readyz(state: State, request: Request, response: Response) -> Health:
    """Readiness: the database answers. Without a real LLM ARIA still works (deterministic).

    It needs no key, for the platform's probes. When the API requires keys, a caller without
    one learns only whether ARIA is ready, not its providers or what its memory holds.
    """
    database = await asyncio.to_thread(_database_ok, state)
    router = state.services.router
    llm = router.has_real_llm("reporter")
    if not database:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    headers = {k.lower(): v for k, v in request.headers.items()}
    detail = state.auth.authenticate(headers) is not None
    if not detail and ("x-api-key" in headers or "authorization" in headers):
        # A wrong key spends the caller's address bucket here too, so /readyz is no way around
        # the limit on guessing keys. Probes send no key and are never limited.
        client = request.client.host if request.client else "unknown"
        allowed, retry_after = state.limiter.allow(f"ip:{client}")
        if not allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "rate limit exceeded",
                headers={"retry-after": str(math.ceil(retry_after))},
            )
    return Health(
        status="ok" if database and llm else "degraded",
        version=__version__,
        database=database,
        llm=llm,
        providers=[s.name for s in router.status() if s.enabled] if detail else None,
        incidents=len(state.services.memory.incidents) if detail else None,
        runbooks=len(state.services.runbooks) if detail else None,
    )


@router.get("/metrics", include_in_schema=False)
async def metrics(state: State) -> Response:
    body = await asyncio.to_thread(state.metrics.render)
    return Response(body, media_type=CONTENT_TYPE)


@router.get("/api/v1/providers", response_model=list[ProviderOut])
async def providers(state: State) -> list[ProviderOut]:
    """LLM providers, their models and circuit-breaker state. Never includes secrets."""
    return [
        ProviderOut.model_validate(s, from_attributes=True) for s in state.services.router.status()
    ]


@router.get("/api/v1/me", response_model=Me)
async def me(state: State, caller: Caller) -> Me:
    """The caller's key name, and whether this API needs a key at all."""
    return Me(
        name=caller.name, authenticated=caller.authenticated, auth_required=not state.auth.open
    )


@router.get("/api/v1/settings", response_model=SettingsOut)
async def settings_view(state: State) -> SettingsOut:
    """Budgets, guardrails, severity, retrieval and routing settings in force. No secrets."""
    settings, config = state.services.settings, state.services.config
    return SettingsOut(
        environment=str(settings.env),
        require_approval=settings.require_approval,
        worker_mode=settings.worker_mode,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        budgets=config.budgets.model_dump(mode="json"),
        guardrails=config.guardrails.model_dump(mode="json"),
        severity={"alpha": config.severity.alpha},
        retrieval=config.retrieval.model_dump(mode="json"),
        investigation=config.investigation.model_dump(mode="json"),
        routing=config.llm.routing,
        embeddings=config.llm.embeddings,
        safety=config.llm.safety,
        channels={
            kind: bool(os.environ.get(channel_env(kind, config.comms), "").strip())
            for kind in ("slack", "teams", "webhook", "status_page", "ticket_draft")
        },
        visitor_keys=accepted_kinds(state),
        visitor_scope=settings.visitor_scope,
    )


_KEY_NAMES = {"claude": "Anthropic", "gemini": "Google", "openai": "OpenAI", "nvidia": "NVIDIA"}


def _refused(company: str, exc: ProviderError) -> str:
    if exc.status in (400, 401, 403, 404):
        return (
            f"{company} did not accept this key (HTTP {exc.status}). Check that you copied all "
            "of it and that it is still active."
        )
    if exc.status == 429:
        return f"{company} is limiting this key's requests right now (HTTP 429). Try again soon."
    return f"{company} could not be reached to check the key. Try again in a minute."


@router.post("/api/v1/model-key/check", response_model=ModelKeyCheck)
async def check_model_key(state: State, visitor: VisitorKeyDep) -> ModelKeyCheck:
    """Check a visitor's own key before it is used, and keep nothing.

    The provider lists its models for the key, which costs nothing. Where that list answers
    anyone (NVIDIA's), one tiny request checks the key instead.
    """
    if visitor is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Send the key in X-Model-Key and its provider in X-Model-Provider.",
        )
    own = state.services.router.with_key(visitor)
    name = own.config.visitor_keys.providers[visitor.provider][0]
    cfg = own.config.providers[name]
    model, company = cfg.chat_model or "", _KEY_NAMES.get(visitor.provider, visitor.provider)
    try:
        if cfg.public_catalog:
            await own.provider(name).chat([Message("user", "Reply with OK.")], max_tokens=16)
            listed = True
        else:
            catalog = await own.provider(name).list_models()
            listed = not catalog or model in catalog
    except ProviderError as exc:
        return ModelKeyCheck(
            provider=visitor.provider, accepted=False, model=model, detail=_refused(company, exc)
        )
    finally:
        await own.aclose()
    detail = (
        f"{company} accepted the key. Runs you start will use {model} first."
        if listed
        else f"{company} accepted the key, but {model} is not among its models, so runs may "
        "fall back to this server's own."
    )
    return ModelKeyCheck(provider=visitor.provider, accepted=True, model=model, detail=detail)
