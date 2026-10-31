"""Alert webhooks and Ask ARIA."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status

from aria.api import alerts as intake
from aria.api.ask import answer, memory_evidence
from aria.api.keys import VisitorKeyDep, may_use_model, offline
from aria.api.schemas import AlertAccepted, AskRequest, AskResponse
from aria.api.state import AppState, app_state
from aria.api.visitors import SEES_ALL, Viewer, ViewerDep
from aria.contracts.base import Evidence
from aria.contracts.inputs import AlertSignal, TriageRequest
from aria.db import repository as repo
from aria.graph.runner import RunNotFoundError

router = APIRouter(prefix="/api/v1", tags=["intake"])
State = Annotated[AppState, Depends(app_state)]
Payload = Annotated[dict[str, Any], Body()]


async def _accept(
    state: AppState, payload: dict[str, Any], source: str, viewer: Viewer
) -> AlertAccepted:
    # Cleaning hundreds of alerts is CPU work: off the event loop, so other requests go on.
    key, alerts, common = await asyncio.to_thread(intake.normalize, payload, source=source)
    if viewer.tag is not None:  # one visitor's alerts never join another visitor's incident
        key = f"{viewer.tag}:{key}"[:256]
    if not alerts:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the payload has no alerts")
    system = intake.system_for(common, alerts)
    window = state.services.config.triggers.alert_group_window_s
    engine = state.services.engine
    found = await asyncio.to_thread(
        intake.record_alerts, engine, key, alerts, system=system, window_s=window
    )
    run_id, run = found.run_id, None
    firing = [a for a in alerts if a.status == "firing"]
    if run_id is None and firing:
        request = intake.triage_request(firing, common, system)
        # An alert carries no visitor key: it may use this server's model only within the daily
        # allowance, like a visitor's run (``keys.may_use_model``); past it, it runs offline.
        if not may_use_model(state, None, viewer.tag, request.options.use_llm):
            request = request.model_copy(update={"options": offline(request.options)})
        run_id, run = await _open_run(state, found, request, source, viewer)
    elif run_id is not None:
        run = await asyncio.to_thread(repo.get_run, engine, run_id)
    return AlertAccepted(
        alert_group_id=found.group_id,
        run_id=run_id,
        grouped=found.grouped,
        alerts=len(alerts),
        status=run["status"] if run else "resolved",
    )


async def _open_run(
    state: AppState,
    found: intake.Grouping,
    request: TriageRequest,
    source: str,
    viewer: Viewer = SEES_ALL,
) -> tuple[str, dict[str, Any] | None]:
    """Open the group's run, or find the one a racing request opened: every request tries the
    same IDs in the same order and stops at the first that is free or already the group's."""
    engine = state.services.engine

    async def submit(run_id: str | None) -> tuple[str, dict[str, Any] | None]:
        given = await asyncio.to_thread(
            state.runner.submit,
            request,
            run_id=run_id,
            trigger=source,
            alert_group_id=found.group_id,
            visitor=viewer.tag,
        )
        return given, await asyncio.to_thread(repo.get_run, engine, given)

    for candidate in intake.run_ids_for(found):
        run_id, run = await submit(candidate)
        if run is not None and intake.opened_by(run, found.group_id):
            break
    else:  # some other run holds every one of those IDs
        run_id, run = await submit(None)
    attached = await asyncio.to_thread(intake.attach_run, engine, found.group_id, run_id)
    if attached != run_id:  # another run became the group's first: this one is not needed
        await state.runner.delete(run_id)
        run_id, run = attached, await asyncio.to_thread(repo.get_run, engine, attached)
    elif state.inprocess:
        state.worker.execute(run_id)
    return run_id, run


@router.post("/alerts/alertmanager", status_code=status.HTTP_202_ACCEPTED)
async def alertmanager(payload: Payload, state: State, viewer: ViewerDep) -> AlertAccepted:
    """A Prometheus Alertmanager webhook (``webhook_configs``)."""
    return await _accept(state, payload, "alertmanager", viewer)


@router.post("/alerts/grafana", status_code=status.HTTP_202_ACCEPTED)
async def grafana(payload: Payload, state: State, viewer: ViewerDep) -> AlertAccepted:
    """A Grafana alerting webhook contact point (same alert shape as Alertmanager)."""
    return await _accept(state, payload, "grafana", viewer)


@router.post("/alerts", status_code=status.HTTP_202_ACCEPTED)
async def alerts(signals: list[AlertSignal], state: State, viewer: ViewerDep) -> AlertAccepted:
    """ARIA's own alert format, for sources without an Alertmanager-style webhook."""
    payload: dict[str, Any] = {
        "alerts": [
            {
                "status": s.status,
                "labels": {"alertname": s.name, **s.labels},
                "annotations": s.annotations,
                "fingerprint": s.fingerprint,
                "startsAt": s.starts_at.isoformat() if s.starts_at else None,
            }
            for s in signals
        ]
    }
    if signals:
        named = [{"alertname": s.name, **s.labels}.items() for s in signals]
        payload["commonLabels"] = dict(set.intersection(*(set(items) for items in named)))
    return await _accept(state, payload, "webhook", viewer)


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest, state: State, visitor: VisitorKeyDep, viewer: ViewerDep
) -> AskResponse:
    """Ask about a run (its evidence) or about incident history (memory search)."""
    services = state.services
    evidence: list[Evidence]
    run = (
        await asyncio.to_thread(repo.get_run, services.engine, body.run_id) if body.run_id else None
    )
    if body.run_id:
        if run is None or not viewer.can_see(run):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {body.run_id} not found")
        try:
            snapshot = await state.runner.snapshot(body.run_id)
        except RunNotFoundError as exc:  # queued, or not yet at its first checkpoint
            detail = f"run {body.run_id} is {run['status']} and has no evidence yet; ask again soon"
            raise HTTPException(status.HTTP_409_CONFLICT, detail) from exc
        evidence = [Evidence.model_validate(e) for e in snapshot.values.get("evidence", [])]
    else:
        evidence = await memory_evidence(services, body.question)
    use_llm = not (run and run.get("request", {}).get("options", {}).get("use_llm") is False)
    use_llm = may_use_model(state, visitor, viewer.tag, use_llm)
    own = services.router.with_key(visitor) if visitor is not None else None
    try:
        output, cited, model = await answer(
            services, body.question, evidence, use_llm=use_llm, router=own
        )
    finally:
        if own is not None:
            await own.aclose()
    referenced = {eid for claim in output.answer for eid in claim.evidence_ids}
    return AskResponse(
        answer=output.answer,
        insufficient_evidence=output.insufficient_evidence,
        follow_ups=output.follow_ups,
        evidence=[item for item in cited if item.id in referenced] or cited[:5],
        answered_by="llm" if model else "retrieval",
        model=model,
    )
