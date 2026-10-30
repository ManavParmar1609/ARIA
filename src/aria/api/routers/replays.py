"""Real incidents to replay: real logs, with their experts' labels, run through ARIA."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from aria.api.schemas import (
    ExpertCheckOut,
    FlaggedUnit,
    RealIncidentOut,
    ReplayRequest,
    RunAccepted,
    RunId,
    links_for,
)
from aria.api.state import AppState, app_state
from aria.contracts.inputs import TriageRequest
from aria.contracts.parsing import FlowCheck
from aria.contracts.run import RunStatus
from aria.data.real import REAL_INCIDENTS, RealIncident, real_incident
from aria.db import repository as repo
from aria.graph.runner import RunNotFoundError

router = APIRouter(prefix="/api/v1/real-incidents", tags=["real incidents"])
runs_router = APIRouter(prefix="/api/v1/runs", tags=["real incidents"])
State = Annotated[AppState, Depends(app_state)]


def _out(incident: RealIncident) -> RealIncidentOut:
    lines, units, failed = incident.counts()
    return RealIncidentOut(
        id=incident.id,
        title=incident.title,
        system=incident.system,
        summary=incident.summary,
        source=incident.source,
        citation=incident.citation,
        lines=lines,
        unit=incident.unit,
        units=units,
        labelled_failures=failed,
    )


@router.get("", response_model=list[RealIncidentOut])
async def list_real_incidents() -> list[RealIncidentOut]:
    """The real incidents this server can replay (their logs ship with ARIA)."""
    available = await asyncio.to_thread(lambda: [i for i in REAL_INCIDENTS if i.available])
    return await asyncio.to_thread(lambda: [_out(i) for i in available])


@router.post(
    "/{incident_id}/replay", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted
)
async def replay_real_incident(
    incident_id: str, state: State, body: ReplayRequest | None = None
) -> RunAccepted:
    """Triage a real incident's logs as a normal run; follow it on ``links.stream``."""
    incident = real_incident(incident_id)
    if incident is None or not await asyncio.to_thread(lambda: incident.available):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no real incident {incident_id}")
    lines = await asyncio.to_thread(incident.lines)
    request = TriageRequest(
        system=incident.system,
        logs=lines,
        options=(body or ReplayRequest()).options,
        replay_of=incident.id,
    )
    run_id = await asyncio.to_thread(state.runner.submit, request, trigger="replay")
    if state.inprocess:
        state.worker.execute(run_id)
    return RunAccepted(run_id=run_id, status=str(RunStatus.QUEUED), links=links_for(run_id))


@runs_router.get("/{run_id}/expert-check", response_model=ExpertCheckOut)
async def expert_check(run_id: RunId, state: State) -> ExpertCheckOut:
    """For a replayed real incident: the units ARIA flagged, with the experts' label for each."""
    run = await asyncio.to_thread(repo.get_run, state.services.engine, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    try:
        values = (await state.runner.snapshot(run_id)).values
    except RunNotFoundError:  # queued, or started without a checkpoint yet: not ready, not missing
        values = {}
    # Until the graph has read it, the request is the one the run recorded.
    request = values.get("request") or run.get("request")
    incident = real_incident(str((request or {}).get("replay_of") or ""))
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this run does not replay a real incident")
    labels = await asyncio.to_thread(incident.labels)
    _, units, failed = await asyncio.to_thread(incident.counts)
    batch = values.get("batch")
    flows = FlowCheck.model_validate(batch.get("flows") or {}) if batch else FlowCheck()
    examples = {e.key: e for e in flows.examples}
    flagged = [
        FlaggedUnit(
            key=key,
            reason=examples[key].reason if key in examples else None,
            evidence_id=examples[key].evidence_id if key in examples else None,
            failed=labels.get(key),
        )
        for key in flows.broken_keys
    ]
    return ExpertCheckOut(
        incident_id=incident.id,
        title=incident.title,
        unit=incident.unit,
        citation=incident.citation,
        ready=batch is not None,
        flagged=flagged,
        flagged_failed=sum(1 for f in flagged if f.failed),
        flagged_healthy=sum(1 for f in flagged if f.failed is False),
        units=units,
        labelled_failures=failed,
    )
