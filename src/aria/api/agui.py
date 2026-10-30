"""AG-UI endpoint: drive a triage run from any AG-UI client (CopilotKit and others).

``POST /agui`` takes a ``RunAgentInput``. The AG-UI thread is the ARIA run:

* a new thread starts triage. The request is ``forwardedProps.request`` or ``state.request``
  (a TriageRequest), or else the last user message, read as log lines;
* a thread paused for review resumes with a ``resume`` entry that answers the review
  interrupt; its payload is a review decision (``approve``, ``edit`` or ``reject``).

The response is an AG-UI event stream: ``RUN_STARTED``; a step per graph node; ``TOOL_CALL_*``
events for the investigator's MCP calls; the report as an assistant text message; ``CUSTOM``
events for ARIA's own signals (``aria.replan``, ``aria.guardrail``, ``aria.token`` …); a
``STATE_SNAPSHOT``; and ``RUN_FINISHED``, whose outcome is ``interrupt`` while the report waits
for review.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator
from typing import Annotated, Any

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    Interrupt,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.core.events import RunFinishedInterruptOutcome, RunFinishedSuccessOutcome
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from aria.api.schemas import ReviewRequest, links_for
from aria.api.security import Principal
from aria.api.state import AppState, app_state, current_principal
from aria.contracts.base import first_problem
from aria.contracts.inputs import TriageRequest
from aria.contracts.report import ReviewDecision
from aria.contracts.run import RunEvent, RunStatus
from aria.db import repository as repo
from aria.graph.runner import RunOutcome, TriageRunner

router = APIRouter(tags=["ag-ui"])
# A thread id that is a valid run id names its run; "." or ".." would be a path the console
# cannot open, so an id must start with a letter or digit.
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_CHUNK = 400


def run_id_for(thread_id: str) -> str:
    """The ARIA run behind an AG-UI thread: the thread id itself when it is a valid run id."""
    if _RUN_ID.fullmatch(thread_id):
        return thread_id
    return "agui-" + hashlib.sha256(thread_id.encode()).hexdigest()[:20]


def _user_text(run_input: RunAgentInput) -> str:
    for message in reversed(run_input.messages):
        if getattr(message, "role", None) != "user":
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(getattr(part, "text", "") for part in content)
        return ""
    return ""


def _follows_up(run_input: RunAgentInput) -> bool:
    """True when the newest message is the user's, written after ARIA had already answered."""
    roles = [getattr(message, "role", None) for message in run_input.messages]
    return bool(roles) and roles[-1] == "user" and "assistant" in roles


def triage_request_from(run_input: RunAgentInput) -> TriageRequest | None:
    for source in (run_input.forwarded_props, run_input.state):
        if isinstance(source, dict) and isinstance(source.get("request"), dict):
            return TriageRequest.model_validate(source["request"])
    text = _user_text(run_input).strip()
    if not text:
        return None
    props = run_input.forwarded_props if isinstance(run_input.forwarded_props, dict) else {}
    lines = [line for line in text.splitlines() if line.strip()]
    return TriageRequest(
        system=str(props.get("system") or "generic"),
        logs=lines,
        synthetic=props.get("synthetic") is True,  # a sample the console loaded
    )


async def pending_interrupt(runner: TriageRunner, run_id: str) -> tuple[str, Any] | None:
    snapshot = await runner.graph.aget_state(runner.config(run_id))
    for task in snapshot.tasks:
        for item in task.interrupts:
            return str(item.id), item.value
    return None


def review_interrupt(interrupt_id: str, payload: dict[str, Any]) -> Interrupt:
    return Interrupt(
        id=interrupt_id,
        reason="review",
        message=payload.get("error")
        or "Review the incident report: approve it, edit it, or reject it.",
        response_schema=ReviewRequest.model_json_schema(),
        metadata=payload,
    )


def snapshot_state(values: dict[str, Any], run: dict[str, Any] | None) -> dict[str, Any]:
    severity = values.get("severity") or {}
    report = values.get("report") or {}
    investigation = values.get("investigation") or {}
    run_id = values.get("run_id", "")
    return {
        "runId": run_id,
        "status": (run or {}).get("status") or values.get("status"),
        "severity": {
            k: severity.get(k)
            for k in ("severity", "decided_by", "confidence", "prediction_set", "needs_review")
        },
        "report": {
            "reportId": report.get("report_id"),
            "title": report.get("title"),
            "status": report.get("status"),
            "generatedBy": report.get("generated_by"),
            "summary": [claim.get("text") for claim in report.get("summary", [])],
        },
        "actions": [
            {k: a.get(k) for k in ("action_id", "kind", "audience", "title", "status")}
            for a in values.get("actions", [])
        ],
        "investigation": {
            "leading": investigation.get("leading_hypothesis"),
            "hypotheses": [
                {k: h.get(k) for k in ("id", "statement", "status", "confidence")}
                for h in investigation.get("hypotheses", [])
            ],
        },
        "similarIncidents": [
            i.get("incident_id") for i in (values.get("retrieval") or {}).get("incidents", [])
        ],
        "links": links_for(run_id).model_dump() if run_id else {},
    }


class Translator:
    """ARIA run events → AG-UI events."""

    def __init__(self, runner: TriageRunner, run_id: str) -> None:
        self.runner = runner
        self.run_id = run_id

    async def report_message(self, report_id: str | None) -> list[BaseEvent]:
        stored = await asyncio.to_thread(
            repo.get_report, self.runner.engine, report_id or f"rpt-{self.run_id}"
        )
        if stored is None:
            return []
        _, markdown = stored
        message_id = f"{report_id}-v{stored[0].version}"
        events: list[BaseEvent] = [TextMessageStartEvent(message_id=message_id, role="assistant")]
        events += [
            TextMessageContentEvent(message_id=message_id, delta=markdown[i : i + _CHUNK])
            for i in range(0, len(markdown), _CHUNK)
        ]
        events.append(TextMessageEndEvent(message_id=message_id))
        return events

    async def translate(self, event: RunEvent) -> list[BaseEvent]:
        payload = event.payload
        node = event.node or ""
        match event.kind:
            case "node_started":
                return [StepStartedEvent(step_name=node)]
            case "node_finished":
                out: list[BaseEvent] = [StepFinishedEvent(step_name=node)]
                if node in ("report", "publish", "reject"):
                    out += await self.report_message(payload.get("report_id"))
                return out
            case "tool_call" if payload.get("phase") == "start":
                ref = str(payload.get("ref"))
                return [
                    ToolCallStartEvent(tool_call_id=ref, tool_call_name=str(payload.get("tool"))),
                    ToolCallArgsEvent(
                        tool_call_id=ref, delta=json.dumps(payload.get("arguments") or {})
                    ),
                    ToolCallEndEvent(tool_call_id=ref),
                ]
            case "tool_call":
                ref = str(payload.get("ref"))
                content = json.dumps({k: payload.get(k) for k in ("ok", "summary", "evidence_ids")})
                return [
                    ToolCallResultEvent(
                        message_id=f"tool-{ref}", tool_call_id=ref, content=content, role="tool"
                    )
                ]
            case "interrupt":
                return [StepFinishedEvent(step_name=node)]  # the step pauses; RUN_FINISHED says why
            case "run_started" | "run_finished" | "error":
                return []  # the stream's own lifecycle events cover these
            case _:
                return [CustomEvent(name=f"aria.{event.kind}", value=payload)]


async def _stream(
    state: AppState, run_input: RunAgentInput, caller: Principal, encoder: EventEncoder
) -> AsyncIterator[str]:
    runner = state.runner
    run_id = run_id_for(run_input.thread_id)
    yield encoder.encode(RunStartedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id))

    def error(message: str, code: str) -> str:
        return encoder.encode(RunErrorEvent(message=message, code=code))

    existing = await asyncio.to_thread(repo.get_run, runner.engine, run_id)
    queue = runner.subscribe(run_id)
    try:
        if run_input.resume:
            pending = await pending_interrupt(runner, run_id) if existing else None
            entry = run_input.resume[0]
            if pending is None or entry.interrupt_id != pending[0]:
                yield error("no review is waiting for that interrupt", "stale_interrupt")
                return
            body = entry.payload if isinstance(entry.payload, dict) else {}
            if entry.status == "cancelled":
                body = {"decision": "reject", "comment": "review cancelled"}
            try:
                review = ReviewRequest.model_validate(body)
            except ValidationError as exc:
                yield error(f"invalid review: {first_problem(exc)}", "bad_review")
                return
            decision = ReviewDecision(
                decision=review.decision,
                reviewer=caller.name if caller.authenticated else (review.reviewer or "agui"),
                comment=review.comment,
                edits=review.edits,
                approve_actions=review.approve_actions,
            )
            job = runner.resume(run_id, decision)
        elif existing is None:
            try:
                request = triage_request_from(run_input)
            except ValidationError as exc:
                yield error(f"invalid request: {first_problem(exc)}", "bad_request")
                return
            if request is None:
                yield error(
                    "send log lines as a user message, or forwardedProps.request", "no_input"
                )
                return
            await asyncio.to_thread(
                runner.submit, request, run_id=run_id, trigger="agui", claim=True
            )
            job = runner.execute(run_id)
        elif RunStatus(existing["status"]).terminal and _follows_up(run_input):
            # One thread is one triage: new logs on a finished thread would be silently dropped.
            yield error(
                f"this thread's run is {existing['status']}; start a new thread to triage new logs",
                "thread_finished",
            )
            return
        else:
            job = runner.execute(run_id)  # continue, or report where the run already stands

        translator = Translator(runner, run_id)
        task: asyncio.Task[RunOutcome] = asyncio.create_task(state.worker.gated(job))
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                for event in await translator.translate(getter.result()):
                    yield encoder.encode(event)
            else:
                getter.cancel()
            if task in done:
                while not queue.empty():
                    for event in await translator.translate(queue.get_nowait()):
                        yield encoder.encode(event)
                break
        try:
            outcome = task.result()
        except Exception as exc:  # reported to the client as RUN_ERROR
            yield error(f"{type(exc).__name__}: {exc}"[:500], "run_failed")
            return

        snapshot = await runner.graph.aget_state(runner.config(run_id))
        run = await asyncio.to_thread(repo.get_run, runner.engine, run_id)
        yield encoder.encode(StateSnapshotEvent(snapshot=snapshot_state(snapshot.values, run)))
        if outcome.status is RunStatus.FAILED:
            yield error(outcome.error or "the run failed", "run_failed")
            return
        finished: RunFinishedEvent
        pending = await pending_interrupt(runner, run_id)
        if outcome.status is RunStatus.AWAITING_REVIEW and pending is not None:
            finished = RunFinishedEvent(
                thread_id=run_input.thread_id,
                run_id=run_input.run_id,
                outcome=RunFinishedInterruptOutcome(
                    interrupts=[review_interrupt(pending[0], pending[1])]
                ),
            )
        else:
            finished = RunFinishedEvent(
                thread_id=run_input.thread_id,
                run_id=run_input.run_id,
                result={"status": str(outcome.status), "run_id": run_id},
                outcome=RunFinishedSuccessOutcome(),
            )
        yield encoder.encode(finished)
    finally:
        runner.unsubscribe(run_id, queue)


@router.post("/agui")
async def agui(
    request: Request,
    state: Annotated[AppState, Depends(app_state)],
    caller: Annotated[Principal, Depends(current_principal)],
) -> StreamingResponse:
    """Run (or resume) ARIA as an AG-UI agent."""
    try:
        run_input = RunAgentInput.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "expected a RunAgentInput"
        ) from exc
    encoder = EventEncoder(accept=request.headers.get("accept", "text/event-stream"))
    return StreamingResponse(
        _stream(state, run_input, caller, encoder),
        media_type=encoder.get_content_type(),
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
