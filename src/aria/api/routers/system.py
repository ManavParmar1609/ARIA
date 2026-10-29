"""Liveness, readiness, metrics and LLM provider status."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from aria import __version__
from aria.api.metrics import CONTENT_TYPE
from aria.api.schemas import Health, Me, ProviderOut, SettingsOut
from aria.api.security import Principal
from aria.api.state import AppState, app_state, current_principal
from aria.db.engine import session_scope

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
async def readyz(state: State, response: Response) -> Health:
    """Readiness: the database answers. Without a real LLM ARIA still works (deterministic)."""
    database = await asyncio.to_thread(_database_ok, state)
    router = state.services.router
    providers = [s.name for s in router.status() if s.enabled]
    llm = router.has_real_llm("reporter")
    if not database:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Health(
        status="ok" if database and llm else "degraded",
        version=__version__,
        database=database,
        llm=llm,
        providers=providers,
        incidents=len(state.services.memory.incidents),
        runbooks=len(state.services.runbooks),
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
    )
