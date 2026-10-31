"""Triage runs: create, inspect, stream, review, time-travel, fork and delete."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from aria.api.keys import VisitorKeyDep
from aria.api.schemas import (
    Checkpoint,
    Delivery,
    ForkRequest,
    ReportOut,
    ReviewRequest,
    RunAccepted,
    RunDetail,
    RunId,
    RunPage,
    RunSummary,
    links_for,
)
from aria.api.security import Principal
from aria.api.sse import run_events
from aria.api.state import AppState, app_state, current_principal
from aria.api.visitors import Viewer, ViewerDep
from aria.contracts.inputs import TriageRequest
from aria.contracts.report import ReviewDecision
from aria.contracts.run import RunEvent, RunStatus
from aria.db import repository as repo
from aria.graph.runner import RunBusyError, RunNotFoundError, RunStateError
from aria.graph.workflow import window_exists
from aria.reporting.markdown import render_postmortem

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
State = Annotated[AppState, Depends(app_state)]
MAX_SEQ = 2**53  # event cursors past this cannot be stored, or read exactly in JavaScript
_EVENT_ID = re.compile(r"[0-9]{1,15}")
Caller = Annotated[Principal, Depends(current_principal)]


async def _run_or_404(state: AppState, run_id: str, viewer: Viewer) -> dict[str, Any]:
    """The run, if this caller may see it: another visitor's run is as missing as no run."""
    run = await asyncio.to_thread(repo.get_run, state.services.engine, run_id)
    if run is None or not viewer.can_see(run):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return run


def _public_state(values: dict[str, Any]) -> dict[str, Any]:
    """Graph state without the raw input lines (the parsed, redacted batch is kept)."""
    out = dict(values)
    request = dict(out.get("request") or {})
    if "logs" in request:
        request["logs"] = {"lines": len(request["logs"]), "omitted": True}
    out["request"] = request
    return out


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def create_run(
    request: TriageRequest, state: State, caller: Caller, visitor: VisitorKeyDep, viewer: ViewerDep
) -> RunAccepted:
    """Start triage. The run continues in the background; follow it on ``links.stream``."""
    wanted, llm = request.options.provider, state.services.router
    keyed = visitor is not None and wanted in llm.config.visitor_keys.providers[visitor.provider]
    if wanted is not None and not keyed and not llm.can_chat(wanted):
        known = llm.config.providers
        if wanted not in known:
            detail = f"unknown provider {wanted!r}; this server knows {', '.join(known)}"
        elif llm.is_set_up(wanted):
            detail = f"provider {wanted!r} has no chat model, so it cannot run triage steps"
        else:
            detail = (
                f"provider {wanted!r} is not set up on this server: `aria providers check` says why"
            )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    if request.window_id and not request.logs:
        engine = state.services.engine
        if not await asyncio.to_thread(window_exists, engine, request.window_id):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"no stored window {request.window_id!r}: load it with `aria data ingest`, "
                "or send the log lines",
            )
    trigger = "api" if caller.authenticated else "manual"
    run_id = await asyncio.to_thread(
        state.runner.submit, request, trigger=trigger, visitor=viewer.tag
    )
    if visitor is not None:
        state.runner.keys.hold(run_id, visitor)
    if state.inprocess:
        state.worker.execute(run_id)
    return RunAccepted(run_id=run_id, status=str(RunStatus.QUEUED), links=links_for(run_id))


@router.get("", response_model=RunPage)
async def list_runs(
    state: State,
    viewer: ViewerDep,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: datetime | None = None,
) -> RunPage:
    rows = await asyncio.to_thread(
        repo.list_runs,
        state.services.engine,
        limit=limit,
        status=str(run_status) if run_status else None,
        before=before,
        seen_by=viewer.tag,
    )
    runs = [RunSummary.model_validate({**row, "example": viewer.is_example(row)}) for row in rows]
    return RunPage(runs=runs, next_before=runs[-1].created_at if len(runs) == limit else None)


def _deliveries(rows: list[dict[str, Any]]) -> list[Delivery]:
    return [
        Delivery(
            action_id=row["id"],
            kind=row["kind"],
            audience=str((row["payload"] or {}).get("audience") or "responders"),
            title=row["title"],
            status=row["status"],
            approved_by=row["approved_by"],
            sent_at=row["executed_at"],
            problem=(row["result"] or {}).get("error") or (row["result"] or {}).get("reason"),
        )
        for row in rows
        if row["status"] in ("approved", "sent", "failed", "skipped")
    ]


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: RunId, state: State, viewer: ViewerDep) -> RunDetail:
    run = await _run_or_404(state, run_id, viewer)
    rows = await asyncio.to_thread(repo.run_actions, state.services.engine, run_id)
    detail: dict[str, Any] = {
        **run,
        "example": viewer.is_example(run),
        "links": links_for(run_id),
        "deliveries": _deliveries(rows),
    }
    try:
        snapshot = await state.runner.snapshot(run_id)
    except RunNotFoundError:
        return RunDetail.model_validate(detail)
    values = snapshot.values
    interrupts = [i.value for task in snapshot.tasks for i in task.interrupts]
    detail.update(
        review=interrupts[0] if interrupts else None,
        plan=values.get("plan"),
        budget=values.get("budget"),
        notes=values.get("notes", []),
        replan_reasons=values.get("replan_reasons", []),
        errors=values.get("errors", []),
    )
    return RunDetail.model_validate(detail)


@router.get("/{run_id}/state")
async def get_state(
    run_id: RunId, state: State, viewer: ViewerDep, checkpoint_id: str | None = None
) -> dict[str, Any]:
    """The run's graph state (at a checkpoint, if given), without the raw input lines.

    A run that exists but has not written its first checkpoint has an empty state, not a 404: the
    console asks as soon as a run starts, and asks again as its steps finish.
    """
    await _run_or_404(state, run_id, viewer)
    try:
        snapshot = await state.runner.snapshot(run_id, checkpoint_id)
    except RunNotFoundError as exc:
        if checkpoint_id is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such checkpoint") from exc
        return {"values": {}, "next": [], "checkpoint_id": None}
    return {
        "values": _public_state(snapshot.values),
        "next": list(snapshot.next),
        "checkpoint_id": snapshot.config["configurable"].get("checkpoint_id"),
    }


@router.get("/{run_id}/events", response_model=list[RunEvent])
async def list_events(
    run_id: RunId,
    state: State,
    viewer: ViewerDep,
    after: Annotated[int, Query(ge=-1, le=MAX_SEQ)] = -1,
    limit: Annotated[int, Query(ge=1, le=5_000)] = 1_000,
) -> list[RunEvent]:
    await _run_or_404(state, run_id, viewer)
    return await asyncio.to_thread(
        repo.list_events, state.services.engine, run_id, after=after, limit=limit
    )


@router.get("/{run_id}/stream")
async def stream(
    run_id: RunId,
    state: State,
    viewer: ViewerDep,
    *,
    after: Annotated[int, Query(ge=-1, le=MAX_SEQ)] = -1,
    until: Annotated[Literal["finished", "review"], Query()] = "finished",
    last_event_id: Annotated[str | None, Header()] = None,
) -> EventSourceResponse:
    """Server-sent events: stored events after ``Last-Event-ID`` (or ``after``), then live.

    The stream ends when the run finishes, or with ``until=review`` when it pauses for review.
    """
    await _run_or_404(state, run_id, viewer)
    # A browser resends the last id it saw; anything else (not ASCII digits, too long) is ignored.
    start = int(last_event_id) if last_event_id and _EVENT_ID.fullmatch(last_event_id) else after
    events = run_events(state.runner, run_id, after=start, until_review=until == "review")
    return EventSourceResponse(events, ping=15)


async def _report(state: AppState, run_id: str, viewer: Viewer) -> tuple[Any, str]:
    run = await _run_or_404(state, run_id, viewer)
    stored = await asyncio.to_thread(
        repo.get_report, state.services.engine, run.get("report_id") or f"rpt-{run_id}"
    )
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this run has no report yet")
    return stored


@router.get("/{run_id}/report", response_model=ReportOut)
async def get_report(run_id: RunId, state: State, viewer: ViewerDep) -> ReportOut:
    report, markdown = await _report(state, run_id, viewer)
    return ReportOut(report=report, markdown=markdown)


@router.get("/{run_id}/report.md", response_class=PlainTextResponse)
async def get_report_markdown(run_id: RunId, state: State, viewer: ViewerDep) -> PlainTextResponse:
    _, markdown = await _report(state, run_id, viewer)
    return PlainTextResponse(markdown, media_type="text/markdown; charset=utf-8")


@router.get("/{run_id}/postmortem.md", response_class=PlainTextResponse)
async def get_postmortem(run_id: RunId, state: State, viewer: ViewerDep) -> PlainTextResponse:
    report, _ = await _report(state, run_id, viewer)
    return PlainTextResponse(render_postmortem(report), media_type="text/markdown; charset=utf-8")


@router.post("/{run_id}/review", response_model=RunDetail)
async def review(
    run_id: RunId, body: ReviewRequest, state: State, caller: Caller, viewer: ViewerDep
) -> RunDetail:
    """Approve, edit or reject the report. Approved actions are sent before this returns."""
    run = await _run_or_404(state, run_id, viewer)
    viewer.refuse_example(run)
    reviewer = caller.name if caller.authenticated else (body.reviewer or caller.name)
    decision = ReviewDecision(
        decision=body.decision,
        reviewer=reviewer,
        comment=body.comment,
        edits=body.edits,
        approve_actions=body.approve_actions,
    )
    try:
        outcome = await state.runner.resume(run_id, decision)
    except RunNotFoundError as exc:  # the run exists, but its graph has not reached review yet
        detail = f"run {run_id} is {run['status']}, not waiting for review"
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from exc
    except (RunStateError, RunBusyError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if outcome.interrupt and outcome.interrupt.get("error"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, outcome.interrupt["error"])
    return await get_run(run_id, state, viewer)


@router.post("/{run_id}/actions/{action_id}/resend", response_model=RunDetail)
async def resend_action(
    run_id: RunId, action_id: RunId, state: State, caller: Caller, viewer: ViewerDep
) -> RunDetail:
    """Send an approved message again after it did not go out: its delivery failed, or the
    process sending it stopped before it heard back. Nothing else is ever resent."""
    viewer.refuse_example(await _run_or_404(state, run_id, viewer))
    try:
        await state.runner.resend(run_id, action_id, by=caller.name)
    except RunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc.args[0])) from exc
    except (RunStateError, RunBusyError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await get_run(run_id, state, viewer)


@router.get("/{run_id}/history", response_model=list[Checkpoint])
async def history(
    run_id: RunId, state: State, viewer: ViewerDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[Checkpoint]:
    """Checkpoints, newest first: fork from any of them."""
    await _run_or_404(state, run_id, viewer)
    items = await state.runner.history(run_id, limit=limit)
    return [Checkpoint.model_validate(item) for item in items]


@router.post("/{run_id}/fork", status_code=status.HTTP_202_ACCEPTED, response_model=RunAccepted)
async def fork(
    run_id: RunId, body: ForkRequest, state: State, visitor: VisitorKeyDep, viewer: ViewerDep
) -> RunAccepted:
    """Branch a new run from a checkpoint, optionally with different run options. The new run is
    the caller's own, so forking an example is how a visitor gets a copy to change."""
    await _run_or_404(state, run_id, viewer)
    try:
        outcome = await state.runner.fork(
            run_id,
            body.checkpoint_id,
            options=body.run_options(),
            title=body.title,
            execute=False,
            visitor=viewer.tag,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such checkpoint") from exc
    except RunStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if visitor is not None:
        state.runner.keys.hold(outcome.run_id, visitor)
    if state.inprocess:
        state.worker.execute(outcome.run_id)
    return RunAccepted(
        run_id=outcome.run_id, status=str(outcome.status), links=links_for(outcome.run_id)
    )


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: RunId, state: State, viewer: ViewerDep) -> None:
    """Delete the run and everything derived from it (report, events, memory, checkpoints)."""
    run = await _run_or_404(state, run_id, viewer)
    viewer.refuse_example(run)
    if run["status"] in (RunStatus.RUNNING, RunStatus.QUEUED):
        raise HTTPException(status.HTTP_409_CONFLICT, "the run is still in progress")
    try:
        await state.runner.delete(run_id)
    except RunBusyError as exc:  # a review is being applied right now
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
