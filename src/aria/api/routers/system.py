"""Liveness, readiness, metrics and LLM provider status."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from aria import __version__
from aria.api.metrics import CONTENT_TYPE
from aria.api.schemas import Health, ProviderOut
from aria.api.state import AppState, app_state
from aria.db.engine import session_scope

router = APIRouter(tags=["system"])
State = Annotated[AppState, Depends(app_state)]


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
