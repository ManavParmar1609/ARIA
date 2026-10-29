"""A2A server: other agents can hand ARIA an incident and get back a reviewed report.

The Agent Card is served at ``/.well-known/agent-card.json`` and the JSON-RPC endpoint at
``/a2a``. Each A2A task is one ARIA run (``a2a-<task id>``):

* the first message carries log lines as text, or a TriageRequest as a data part;
* the task goes ``working`` → ``input-required`` once the report waits for review, with the
  report attached as an artifact and the review request as a data part;
* a follow-up message on the same task answers with a review decision (a data part such as
  ``{"decision": "approve"}``, or the text ``approve`` / ``reject``), and the task completes when
  the report is published or rejected.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from a2a.helpers.proto_helpers import (
    get_data_parts,
    get_text_parts,
    new_data_part,
    new_task_from_user_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    HTTPAuthSecurityScheme,
    Message,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.errors import TaskNotCancelableError
from pydantic import ValidationError
from starlette.requests import Request
from starlette.routing import BaseRoute

from aria import __version__
from aria.config import Settings
from aria.contracts.inputs import TriageRequest
from aria.contracts.report import ReviewDecision
from aria.contracts.run import RunStatus
from aria.db import repository as repo
from aria.graph.runner import RunOutcome, TriageRunner

A2A_PATH = "/a2a"
_REQUEST_KEYS = frozenset({"logs", "alerts", "window_id", "ticket"})


def agent_card(settings: Settings, *, secured: bool) -> AgentCard:
    base = settings.public_base_url.rstrip("/")
    card = AgentCard(
        name="ARIA",
        description=(
            "First-pass incident triage. ARIA parses logs and alerts, rates severity with "
            "calibrated confidence, finds similar past incidents, investigates with read-only "
            "tools and writes a report in which every claim cites its evidence. A human reviews "
            "the report before anything is published or sent."
        ),
        version=__version__,
        supported_interfaces=[
            AgentInterface(
                url=f"{base}{A2A_PATH}", protocol_binding="JSONRPC", protocol_version="1.0"
            )
        ],
        provider=AgentProvider(
            organization="ARIA (open source)", url="https://github.com/ManavParmar1609/ARIA"
        ),
        documentation_url=f"{base}/docs",
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["application/json", "text/markdown"],
        skills=[
            AgentSkill(
                id="incident-triage",
                name="Incident triage",
                description=(
                    "Triage an incident from raw log lines (text) or a TriageRequest (data). "
                    "Returns a cited incident report and pauses for a reviewer's decision."
                ),
                tags=["incident-response", "sre", "triage", "logs", "severity"],
                examples=[
                    "<paste 200 log lines from the failing service>",
                    '{"system": "hdfs", "logs": ["..."], "title": "Block serve errors"}',
                ],
                input_modes=["text/plain", "application/json"],
                output_modes=["application/json", "text/markdown"],
            )
        ],
    )
    if secured:
        card.security_schemes["bearer"].CopyFrom(
            SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(
                    scheme="Bearer", description="An ARIA API key"
                )
            )
        )
        card.security_requirements.append(SecurityRequirement(schemes={"bearer": StringList()}))
    return card


def request_from(message: Message, metadata: dict[str, Any]) -> TriageRequest:
    for item in get_data_parts(message.parts):
        if isinstance(item, dict) and _REQUEST_KEYS & item.keys():
            return TriageRequest.model_validate(item)
    text = "\n".join(get_text_parts(message.parts)).strip()
    if not text:
        msg = "send log lines as text, or a TriageRequest as a data part"
        raise ValueError(msg)
    lines = [line for line in text.splitlines() if line.strip()]
    return TriageRequest(
        system=str(metadata.get("system") or "generic"),
        title=metadata.get("title"),
        logs=lines,
    )


def decision_from(message: Message, reviewer: str) -> ReviewDecision:
    for item in get_data_parts(message.parts):
        if isinstance(item, dict) and "decision" in item:
            return ReviewDecision.model_validate({**item, "reviewer": reviewer})
    word = " ".join(get_text_parts(message.parts)).strip().lower()
    if word in ("approve", "reject"):
        return ReviewDecision(decision=word, reviewer=reviewer)  # type: ignore[arg-type]
    msg = 'answer with {"decision": "approve" | "edit" | "reject"} or the word approve or reject'
    raise ValueError(msg)


class PrincipalContextBuilder(DefaultServerCallContextBuilder):
    """Hands the caller the API key identified (set by the auth middleware) to the executor."""

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        principal = getattr(request.state, "principal", None)
        if principal is not None:
            context.state["principal"] = principal
        return context


def reviewer_for(context: RequestContext, claimed: object) -> str:
    """Who reviews: the API key's name when keys are on (as over REST), else what the client says."""
    principal = context.call_context.state.get("principal") if context.call_context else None
    if principal is not None and principal.authenticated:
        return str(principal.name)
    return str(claimed or "a2a")


class AriaExecutor(AgentExecutor):
    """Runs A2A tasks as ARIA runs. The runner is looked up per task (it starts with the app)."""

    def __init__(self, get_runner: Callable[[], TriageRunner]) -> None:
        self._get_runner = get_runner

    @property
    def runner(self) -> TriageRunner:
        return self._get_runner()

    @staticmethod
    def run_id(task_id: str) -> str:
        return f"a2a-{task_id}"[:64]

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        if message is None:
            return
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        run_id = self.run_id(task.id)
        metadata = {**dict(message.metadata.items()), **context.metadata}
        run = await asyncio.to_thread(repo.get_run, self.runner.engine, run_id)
        if run is not None and run["status"] == RunStatus.AWAITING_REVIEW:
            reviewer = reviewer_for(context, metadata.get("reviewer"))
            try:
                decision = decision_from(message, reviewer)
            except (ValueError, ValidationError) as exc:
                await updater.requires_input(updater.new_agent_message([new_text_part(str(exc))]))
                return
            outcome = await self.runner.resume(run_id, decision)
        else:
            try:
                request = request_from(message, metadata)
            except (ValueError, ValidationError) as exc:
                await updater.reject(updater.new_agent_message([new_text_part(str(exc))]))
                return
            await updater.start_work(
                updater.new_agent_message([new_text_part("ARIA is triaging the incident.")])
            )
            await asyncio.to_thread(self.runner.submit, request, run_id=run_id, trigger="a2a")
            outcome = await self.runner.execute(run_id)
        await self._finish(updater, outcome)

    async def _attach_report(self, updater: TaskUpdater, run_id: str) -> None:
        stored = await asyncio.to_thread(repo.get_report, self.runner.engine, f"rpt-{run_id}")
        if stored is None:
            return
        report, markdown = stored
        await updater.add_artifact(
            [
                new_data_part(report.model_dump(mode="json"), media_type="application/json"),
                new_text_part(markdown, media_type="text/markdown"),
            ],
            artifact_id=f"{run_id}-report",
            name="incident-report",
        )

    async def _finish(self, updater: TaskUpdater, outcome: RunOutcome) -> None:
        if outcome.status is RunStatus.FAILED:
            text = f"Triage failed: {outcome.error or 'unknown error'}"
            await updater.failed(updater.new_agent_message([new_text_part(text)]))
            return
        await self._attach_report(updater, outcome.run_id)
        if outcome.status is RunStatus.AWAITING_REVIEW:
            ask = "The report is ready for review. Reply with a decision: approve, edit or reject."
            parts = [new_text_part(ask), new_data_part(outcome.interrupt or {})]
            await updater.requires_input(updater.new_agent_message(parts))
        elif outcome.status is RunStatus.REJECTED:
            await updater.complete(updater.new_agent_message([new_text_part("Report rejected.")]))
        else:
            await updater.complete(updater.new_agent_message([new_text_part("Report published.")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or ""
        run_id = self.run_id(task_id)
        run = await asyncio.to_thread(repo.get_run, self.runner.engine, run_id)
        if run is None or run["status"] != RunStatus.AWAITING_REVIEW:
            raise TaskNotCancelableError
        decision = ReviewDecision(
            decision="reject", reviewer=reviewer_for(context, None), comment="task cancelled"
        )
        await self.runner.resume(run_id, decision)
        updater = TaskUpdater(event_queue, task_id, context.context_id or "")
        await updater.cancel()


def a2a_routes(
    get_runner: Callable[[], TriageRunner], settings: Settings, *, secured: bool
) -> tuple[list[BaseRoute], list[BaseRoute]]:
    """The Agent Card routes and the JSON-RPC routes."""
    card = agent_card(settings, secured=secured)
    handler = DefaultRequestHandler(
        agent_executor=AriaExecutor(get_runner), task_store=InMemoryTaskStore(), agent_card=card
    )
    return list(create_agent_card_routes(card)), list(
        create_jsonrpc_routes(handler, rpc_url=A2A_PATH, context_builder=PrincipalContextBuilder())
    )
