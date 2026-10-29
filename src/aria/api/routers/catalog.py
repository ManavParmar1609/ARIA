"""Incident memory and runbooks (read-only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from aria.api.schemas import IncidentOut, RunbookOut, RunbookStep
from aria.api.state import AppState, app_state
from aria.retrieval.memory import MemoryIncident
from aria.retrieval.runbooks import Runbook

router = APIRouter(prefix="/api/v1", tags=["catalog"])
State = Annotated[AppState, Depends(app_state)]


def _incident(item: MemoryIncident, score: float | None = None) -> IncidentOut:
    return IncidentOut(
        incident_id=item.id,
        title=item.title,
        system=item.system,
        failure_mode=item.failure_mode,
        severity=item.severity,
        summary=item.summary,
        resolution=item.resolution,
        runbook_slug=item.runbook_slug,
        occurrences=item.occurrences,
        last_seen=item.last_seen,
        source=item.source,
        synthetic=item.synthetic,
        score=score,
    )


def _runbook(rb: Runbook) -> RunbookOut:
    def steps(items: tuple[object, ...]) -> list[RunbookStep]:
        return [RunbookStep(text=s.text, risk=s.risk) for s in items]  # type: ignore[attr-defined]

    return RunbookOut(
        slug=rb.slug,
        title=rb.title,
        risk=rb.risk,
        systems=list(rb.systems),
        failure_modes=list(rb.failure_modes),
        when_to_use=rb.when,
        diagnose=steps(rb.diagnose),
        mitigate=steps(rb.mitigate),
        verify=steps(rb.verify),
        escalate=rb.escalate,
    )


@router.get("/incidents", response_model=list[IncidentOut])
async def incidents(
    state: State,
    q: Annotated[str | None, Query(min_length=2, max_length=300)] = None,
    system: Annotated[str | None, Query(max_length=48)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[IncidentOut]:
    """Past incidents: hybrid search when ``q`` is given, else the most recent."""
    memory = state.services.memory
    if q:
        hits = await memory.search(q, system=system, candidates=limit)
        return [_incident(item, round(hit.score, 4)) for item, hit in hits[:limit]]
    items = [i for i in memory.incidents.values() if system in (None, i.system)]
    items.sort(key=lambda i: (i.last_seen is not None, i.last_seen), reverse=True)
    return [_incident(item) for item in items[:limit]]


@router.get("/incidents/{incident_id}", response_model=IncidentOut)
async def incident(incident_id: str, state: State) -> IncidentOut:
    item = state.services.memory.get(incident_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"incident {incident_id} not found")
    return _incident(item)


@router.get("/runbooks", response_model=list[RunbookOut])
async def runbooks(state: State, system: str | None = None) -> list[RunbookOut]:
    items = sorted(state.services.runbooks.values(), key=lambda rb: rb.slug)
    return [_runbook(rb) for rb in items if system is None or system in rb.systems or rb.generic]


@router.get("/runbooks/{slug}.md", response_class=PlainTextResponse)
async def runbook_markdown(slug: str, state: State) -> PlainTextResponse:
    rb = state.services.runbooks.get(slug)
    if rb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"runbook {slug} not found")
    return PlainTextResponse(f"# {rb.title}\n\n{rb.body}", media_type="text/markdown")


@router.get("/runbooks/{slug}", response_model=RunbookOut)
async def runbook(slug: str, state: State) -> RunbookOut:
    rb = state.services.runbooks.get(slug)
    if rb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"runbook {slug} not found")
    return _runbook(rb)
