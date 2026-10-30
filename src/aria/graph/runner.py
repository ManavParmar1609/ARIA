"""Runs the triage graph: start, stream, resume after review, history, forks and deletion.

The runner owns a run's lifecycle record (its ``runs`` row and event log); graph nodes own the
domain records (report, actions, tool calls, feedback). Every streamed event is stored with a
per-run sequence number, except LLM tokens, which go only to live subscribers, so a client can
replay a run's events from any point and then follow it live.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import InvalidUpdateError
from langgraph.store.base import BaseStore
from langgraph.types import Command, Overwrite, StateSnapshot, StreamMode
from sqlalchemy import delete

from aria.contracts.inputs import RunOptions, TriageRequest
from aria.contracts.report import IncidentReport, OutboundAction, ReviewDecision
from aria.contracts.run import EventKind, Plan, RunEvent, RunStatus
from aria.db import repository as repo
from aria.db.engine import session_scope
from aria.db.models import FeedbackRow, IncidentRow, LogEventRow, RunRow, ToolCallRow
from aria.graph.checkpoint import SqlCheckpointSaver
from aria.graph.state import Json
from aria.graph.store import SqlStore
from aria.graph.workflow import (
    TriageContext,
    build_graph,
    rekey_for_fork,
    run_link,
    run_salt,
)
from aria.mcp.client import Target
from aria.notify import send_action
from aria.observability.logging import get_logger
from aria.reporting.markdown import render_markdown
from aria.retrieval import runlog
from aria.retrieval.memory import run_incident_id
from aria.security.fields import clean_request
from aria.services import Services

log = get_logger(__name__)
STREAM_MODES: list[StreamMode] = ["tasks", "custom", "checkpoints"]
# A drive that has just paused still settles for a moment (its last events, its claim). A review
# or delete arriving as the run shows "awaiting review" waits that out instead of failing.
SETTLE_WAIT_S = 5.0

# A fork's state update cannot go in front of a step reached by a routed Command, a Send or a
# join: LangGraph drops the pending route, and the fork would stop at once. Those forks start
# from the nearest earlier step that can take an update, which reruns the routing step too. Plan
# and parsing are deterministic, assess is cheap, and a fork in front of publish goes back to
# review, so it never reuses the parent's approval.
FORK_FROM: dict[str, frozenset[str]] = {
    "parse_shard": frozenset({"plan"}),
    "merge": frozenset({"plan"}),
    "investigate": frozenset({"severity", "recall"}),
    "widen": frozenset({"assess"}),
    "report": frozenset({"assess"}),
    "publish": frozenset({"review"}),
    "reject": frozenset({"review"}),
}
_SUBSCRIBER_QUEUE = 2_000


class RunNotFoundError(KeyError):
    pass


class RunBusyError(RuntimeError):
    """The run is executing already, in this process or another one."""


class RunStateError(ValueError):
    """The run is not in a state that allows the operation (e.g. resume without a review)."""


@dataclass
class RunOutcome:
    run_id: str
    status: RunStatus
    interrupt: Json | None = None
    error: str | None = None


def new_run_id() -> str:
    return f"run-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:10]}"


def process_owner() -> str:
    """The name a runner claims runs under: a new one for each runner, even in one process. A
    restarted container keeps its host name and often its pid (1), so a random part keeps the new
    process from taking its dead predecessor's claims for its own. The host name is cut to fit
    the claim column (64 characters) beside a pid and the random part."""
    return f"{socket.gethostname()[:40]}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def summarize(node: str, result: Json) -> Json:
    """A compact, JSON-safe summary of what a node wrote, for the event log."""
    out: Json = {}
    if node == "plan" and result.get("plan"):
        out = {"shards": result["plan"].get("fanout_shards"), "notes": result["plan"].get("notes")}
    elif node == "merge" and result.get("batch"):
        features = result["batch"].get("features", {})
        out = {
            "events": features.get("n_events"),
            "errors": features.get("error_events"),
            "templates": features.get("n_templates"),
            "quarantined": len(result["batch"].get("guard", {}).get("injections", [])),
        }
    elif node == "severity" and result.get("severity"):
        sev = result["severity"]
        keys = ("severity", "decided_by", "confidence", "needs_review", "prediction_set")
        out = {k: sev.get(k) for k in keys}
    elif node in ("recall", "widen") and result.get("retrieval"):
        retrieval = result["retrieval"]
        out = {
            "incidents": [i.get("incident_id") for i in retrieval.get("incidents", [])],
            "grade": retrieval.get("grade"),
        }
    elif node == "investigate" and result.get("investigation"):
        inv = result["investigation"]
        out = {
            "leading": inv.get("leading_hypothesis"),
            "steps": inv.get("steps"),
            "stopped": inv.get("stopped_reason"),
            "hypotheses": [
                {k: h.get(k) for k in ("id", "status", "confidence", "statement")}
                for h in inv.get("hypotheses", [])
            ],
        }
    elif node == "assess":
        out = {"replan_reasons": result.get("replan_reasons", [])}
    elif node == "report" and result.get("report"):
        rep = result["report"]
        out = {
            "report_id": rep.get("report_id"),
            "title": rep.get("title"),
            "generated_by": rep.get("generated_by"),
            "valid": rep.get("validation", {}).get("ok"),
        }
    elif node == "comms":
        out = {"actions": [a.get("action_id") for a in result.get("actions", [])]}
    elif node in ("publish", "reject"):
        out = {
            "status": result.get("status"),
            "actions": {a.get("action_id"): a.get("status") for a in result.get("actions", [])},
        }
    return dict(_jsonable(out or {"keys": sorted(k for k in result if not k.startswith("__"))}))


def run_fields(values: Json) -> Json:
    """Columns of the ``runs`` row that follow from the graph state."""
    fields: Json = {}
    severity = values.get("severity") or {}
    if severity:
        fields.update(
            severity=severity.get("severity"),
            decided_by=severity.get("decided_by"),
            auditable=severity.get("auditable"),
            confidence=severity.get("confidence"),
        )
    budget = values.get("budget") or {}
    if budget:
        fields.update(
            tokens_in=int(budget.get("tokens_in", 0)),
            tokens_out=int(budget.get("tokens_out", 0)),
            cost_usd=float(budget.get("cost_usd", 0.0)),
        )
    report = values.get("report") or {}
    if report:
        fields["report_id"] = report.get("report_id")
        edits = (values.get("review") or {}).get("edits") or {}
        if report.get("title") and (
            edits.get("title") or not (values.get("request") or {}).get("title")
        ):
            # A run started without a title takes its report's; a reviewer's new title wins.
            fields["title"] = str(report["title"])[:300]
    meta = values.get("report_meta") or {}
    if meta.get("provider"):
        fields["providers"] = [f"{meta['provider']}/{meta.get('model')}"]
    errors = values.get("errors") or []
    if errors:
        fields["error"] = f"{errors[-1].get('node')}: {errors[-1].get('error')}"[:2_000]
    return fields


class TriageRunner:
    def __init__(
        self,
        services: Services,
        *,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        store: BaseStore | None = None,
        tools: Target | None = None,
    ) -> None:
        self.services = services
        self.engine = services.engine
        self.checkpointer = checkpointer or SqlCheckpointSaver(services.engine)
        self.store = store or SqlStore(services.engine)
        self.graph = build_graph(checkpointer=self.checkpointer, store=self.store)
        self.context = TriageContext(services=services, tools=tools)
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.observers: list[Callable[[RunEvent], None]] = []  # e.g. metrics
        self._subscribers: defaultdict[str, set[asyncio.Queue[RunEvent]]] = defaultdict(set)
        self._last_seq: dict[str, int] = {}
        # Runs this process has claimed: a run it is driving, or one it took and has yet to start.
        self.owner = process_owner()
        self.held: set[str] = set()

    @staticmethod
    def config(run_id: str, checkpoint_id: str | None = None) -> RunnableConfig:
        configurable: dict[str, Any] = {"thread_id": run_id, "checkpoint_ns": ""}
        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id
        return {"configurable": configurable, "recursion_limit": 80}

    # --- events --------------------------------------------------------------------------------

    def subscribe(self, run_id: str) -> asyncio.Queue[RunEvent]:
        queue: asyncio.Queue[RunEvent] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE)
        self._subscribers[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[RunEvent]) -> None:
        self._subscribers[run_id].discard(queue)
        if not self._subscribers[run_id]:
            self._subscribers.pop(run_id, None)

    def _broadcast(self, event: RunEvent) -> None:
        for queue in list(self._subscribers.get(event.run_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # a slow consumer misses events; it can replay from the DB
                log.warning("runner.subscriber_lagging", run_id=event.run_id)

    async def _event(
        self, run_id: str, kind: EventKind, *, node: str | None = None, payload: Json | None = None
    ) -> RunEvent:
        if kind == "token":  # live only: too many to store, and the report holds the result
            event = RunEvent(
                seq=self._last_seq.get(run_id, 0),
                run_id=run_id,
                kind=kind,
                node=node,
                payload=payload or {},
            )
        else:
            event = await asyncio.to_thread(
                repo.append_event, self.engine, run_id, kind, node=node, payload=payload
            )
            self._last_seq[run_id] = event.seq
        self._broadcast(event)
        for observe in self.observers:
            observe(event)
        return event

    async def _handle(self, run_id: str, part: Mapping[str, Any]) -> None:
        if part.get("ns"):
            return
        kind, data = part["type"], part["data"]
        if kind == "tasks":
            name = str(data["name"])
            if name.startswith("__"):
                return
            if "input" in data:
                await self._event(run_id, "node_started", node=name)
            elif data.get("error"):
                await self._event(
                    run_id, "error", node=name, payload={"error": str(data["error"])[:1_000]}
                )
            elif data.get("interrupts"):
                value = _jsonable(data["interrupts"][0].get("value"))
                await self._event(run_id, "interrupt", node=name, payload=value)
            else:
                await self._event(
                    run_id,
                    "node_finished",
                    node=name,
                    payload=summarize(name, data.get("result") or {}),
                )
        elif kind == "custom" and isinstance(data, dict) and data.get("kind"):
            await self._event(
                run_id,
                data["kind"],
                node=data.get("node"),
                payload=_jsonable(data.get("payload") or {}),
            )
        elif kind == "checkpoints":
            configurable = data["config"]["configurable"]
            await self._event(
                run_id,
                "checkpoint",
                payload={
                    "checkpoint_id": configurable["checkpoint_id"],
                    "step": data["metadata"].get("step"),
                    "source": data["metadata"].get("source"),
                    "next": list(data.get("next") or []),
                },
            )

    # --- lifecycle -----------------------------------------------------------------------------

    def submit(
        self,
        request: TriageRequest,
        *,
        run_id: str | None = None,
        trigger: str = "manual",
        claim: bool = False,
        **fields: Any,
    ) -> str:
        """Record a new run (queued); ``execute`` runs it.

        ``claim`` records the run as this process's from the start, for a run this process will
        execute itself (an AG-UI or A2A stream), so no external worker takes it meanwhile.
        """
        run_id = run_id or new_run_id()
        if claim:
            fields.update(claimed_by=self.owner, claimed_at=datetime.now(UTC))
            self.held.add(run_id)
        if trigger != "replay" and request.replay_of is not None:
            # Only the replay endpoint may tie a run to a real incident's expert labels.
            request = request.model_copy(update={"replay_of": None})
        request = self._cleaned(request, run_id)
        repo.create_run(
            self.engine,
            run_id,
            request=request.model_dump(mode="json"),
            trigger=trigger,
            title=request.title,
            system=request.system,
            status=RunStatus.QUEUED,
            **fields,
        )
        return run_id

    def _cleaned(self, request: TriageRequest, run_id: str) -> TriageRequest:
        """The request with its title, service, alerts and ticket cleaned with the run's key,
        before anything stores it: the run row, the run list and the first checkpoint (which the
        state endpoint can show) never hold a raw secret or instruction. The plan step cleans
        them again, which changes nothing."""
        cleaned, _ = clean_request(
            request,
            self.services.config.guardrails,
            run_salt(self.services.settings, run_id, self.engine),
        )
        return cleaned

    async def execute(self, run_id: str) -> RunOutcome:
        """Run a submitted run, or continue one that stopped (for example after a restart)."""
        run = await asyncio.to_thread(repo.get_run, self.engine, run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        snapshot = await self.graph.aget_state(self.config(run_id))
        if snapshot.values:
            if _interrupts(snapshot) or not snapshot.next:
                try:
                    return await self._settle(run_id)
                finally:  # nothing to drive: give up a claim taken to drive it (a recovery)
                    await self.let_go(run_id)
            return await self._drive(run_id, None)  # crash recovery: continue from the checkpoint
        return await self._drive(
            run_id,
            {"run_id": run_id, "request": run["request"]},
            started={"trigger": run.get("trigger")},
        )

    async def start(self, request: TriageRequest, **kwargs: Any) -> RunOutcome:
        return await self.execute(self.submit(request, **kwargs))

    async def resume(self, run_id: str, decision: ReviewDecision | Json) -> RunOutcome:
        snapshot = await self.graph.aget_state(self.config(run_id))
        if not snapshot.values:
            raise RunNotFoundError(run_id)
        if not _interrupts(snapshot):
            msg = f"run {run_id} is not waiting for a review"
            raise RunStateError(msg)
        value = (
            decision.model_dump(mode="json")
            if isinstance(decision, ReviewDecision)
            else ReviewDecision.model_validate(decision).model_dump(mode="json")
        )
        return await self._drive(run_id, Command(resume=value), review=True)

    def renew_held(self) -> None:
        """Keep this process's claims fresh: on runs it drives and on runs it has yet to start."""
        repo.renew_claims(self.engine, self.owner, sorted(self.held))

    async def let_go(self, run_id: str) -> None:
        """Give up a claim this runner took to drive a run, when no drive started: the request
        was cancelled while it waited for a slot, or the run had nothing left to drive. Without
        this the claim would be renewed for good and no other process could take the run.

        It waits briefly for whatever holds the run here (a resend or a delete). A drive
        releases its own claim when it ends, so after one, or during one, this does nothing."""
        if run_id not in self.held:
            return
        with contextlib.suppress(RunBusyError):  # a drive holds it: it lets go when it ends
            async with self._holding(run_id):
                if run_id in self.held:
                    self.held.discard(run_id)
                    await asyncio.to_thread(repo.release_run, self.engine, run_id, self.owner)

    async def _renew(self, run_id: str) -> None:
        while True:
            await asyncio.sleep(repo.CLAIM_RENEW_S)
            await asyncio.to_thread(repo.renew_claims, self.engine, self.owner, [run_id])

    @contextlib.asynccontextmanager
    async def _holding(self, run_id: str) -> AsyncIterator[None]:
        """Hold the run in this process, waiting briefly for a drive that is settling."""
        lock = self._locks[run_id]
        try:
            await asyncio.wait_for(lock.acquire(), SETTLE_WAIT_S)
        except TimeoutError:
            msg = f"run {run_id} is already running"
            raise RunBusyError(msg) from None
        try:
            yield
        finally:
            lock.release()

    async def _drive(
        self,
        run_id: str,
        graph_input: Any,
        *,
        config: RunnableConfig | None = None,
        started: Json | None = None,
        review: bool = False,
    ) -> RunOutcome:
        async with self._holding(run_id):
            # The claim spans processes: an API resuming a review and a worker recovering a run
            # it thinks abandoned can never drive the same run, so nothing is sent twice. A
            # review claims without marking the run running until it knows the review counts.
            claimed = await asyncio.to_thread(
                repo.claim_run,
                self.engine,
                run_id,
                self.owner,
                status=None if review else RunStatus.RUNNING,
            )
            if not claimed:
                msg = f"run {run_id} is running in another process"
                raise RunBusyError(msg)
            self.held.add(run_id)
            renewal = asyncio.create_task(self._renew(run_id))
            try:
                if review:
                    # Checked again under the claim: of reviews sent at once, the first decides
                    # and the rest find nothing waiting, so a late reject is refused rather
                    # than reported as the outcome of a run another reviewer published.
                    if not _interrupts(await self.graph.aget_state(self.config(run_id))):
                        msg = f"run {run_id} is not waiting for a review"
                        raise RunStateError(msg)
                    await asyncio.to_thread(
                        repo.update_run, self.engine, run_id, status=RunStatus.RUNNING
                    )
                if started is not None:  # only the process that won the run says it started
                    await self._event(run_id, "run_started", payload=started)
                return await self._stream(run_id, graph_input, config)
            finally:
                renewal.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await renewal
                self.held.discard(run_id)
                await asyncio.to_thread(repo.release_run, self.engine, run_id, self.owner)

    async def _stream(
        self, run_id: str, graph_input: Any, config: RunnableConfig | None
    ) -> RunOutcome:
        try:
            async for part in self.graph.astream(
                graph_input,
                config or self.config(run_id),
                context=self.context,
                stream_mode=STREAM_MODES,
                version="v2",
            ):
                await self._handle(run_id, part)
        except Exception as exc:  # the graph's own handler covers node errors; this is the rest
            message = f"{type(exc).__name__}: {exc}"[:2_000]
            log.exception("runner.failed", run_id=run_id)
            await asyncio.to_thread(
                repo.update_run, self.engine, run_id, status=RunStatus.FAILED, error=message
            )
            await self._event(run_id, "error", payload={"error": message})
            await self._event(run_id, "run_finished", payload={"status": str(RunStatus.FAILED)})
            return RunOutcome(run_id, RunStatus.FAILED, error=message)
        return await self._settle(run_id)

    async def _settle(self, run_id: str) -> RunOutcome:
        snapshot = await self.graph.aget_state(self.config(run_id))
        values = snapshot.values
        interrupts = _interrupts(snapshot)
        if interrupts:
            status = RunStatus.AWAITING_REVIEW
        else:
            status = RunStatus(values.get("status") or RunStatus.FAILED)
            if status is RunStatus.RUNNING and not snapshot.next:
                status = RunStatus.FAILED
        fields = run_fields(values)
        run = await asyncio.to_thread(repo.get_run, self.engine, run_id)
        started = (values.get("budget") or {}).get("started_at")
        if run is not None and run.get("latency_ms") is None and started:
            elapsed = datetime.now(UTC) - datetime.fromisoformat(started)
            fields["latency_ms"] = round(elapsed.total_seconds() * 1_000, 1)
        await asyncio.to_thread(repo.update_run, self.engine, run_id, status=status, **fields)
        if "latency_ms" in fields:  # first time the run reached review (or the end)
            budget = values.get("budget") or {}
            await self._event(
                run_id,
                "budget",
                payload={
                    "latency_ms": fields["latency_ms"],
                    "tokens_in": budget.get("tokens_in", 0),
                    "tokens_out": budget.get("tokens_out", 0),
                    "cost_usd": budget.get("cost_usd", 0.0),
                    "llm_calls": budget.get("llm_calls", 0),
                    "tool_calls": budget.get("tool_calls", 0),
                    "exhausted": budget.get("exhausted", []),
                },
            )
        interrupt = _jsonable(interrupts[0]) if interrupts else None
        # Only on the change: settling a finished run again (a client reconnecting) adds nothing.
        if status.terminal and (run is None or run.get("status") != str(status)):
            await self._event(run_id, "run_finished", payload={"status": str(status)})
        return RunOutcome(run_id, status, interrupt=interrupt, error=fields.get("error"))

    # --- inspection, time travel and forks -----------------------------------------------------

    async def snapshot(self, run_id: str, checkpoint_id: str | None = None) -> StateSnapshot:
        snapshot = await self.graph.aget_state(self.config(run_id, checkpoint_id))
        if not snapshot.values:
            raise RunNotFoundError(run_id)
        return snapshot

    async def history(self, run_id: str, *, limit: int = 100) -> list[Json]:
        out: list[Json] = []
        async for snap in self.graph.aget_state_history(self.config(run_id), limit=limit):
            configurable = snap.config["configurable"]
            parent = (snap.parent_config or {}).get("configurable", {})
            out.append(
                {
                    "checkpoint_id": configurable["checkpoint_id"],
                    "parent_checkpoint_id": parent.get("checkpoint_id"),
                    "step": snap.metadata.get("step") if snap.metadata else None,
                    "source": snap.metadata.get("source") if snap.metadata else None,
                    "next": list(snap.next),
                    "created_at": snap.created_at,
                    "status": snap.values.get("status"),
                    "severity": (snap.values.get("severity") or {}).get("severity"),
                    "interrupted": any(task.interrupts for task in snap.tasks),
                }
            )
        return out

    def _save_forked_report(self, update: Json, values: Json) -> None:
        """A fork taken after the report step reruns neither report nor comms: save its re-keyed
        report and drafts now, so the report and its Markdown export exist before approval."""
        if update.get("report"):
            report = IncidentReport.model_validate(update["report"])
            decided_by = (values.get("severity") or {}).get("decided_by")
            markdown = render_markdown(report, decided_by=decided_by)
            repo.save_report(self.engine, report, markdown=markdown)
        if update.get("actions"):
            actions = [OutboundAction.model_validate(raw) for raw in update["actions"]]
            repo.save_actions(self.engine, update["run_id"], actions)

    async def _ancestor(self, run_id: str, checkpoint_id: str, nodes: frozenset[str]) -> str | None:
        """The nearest earlier checkpoint of ``checkpoint_id`` about to run exactly ``nodes``."""
        by_id = {h["checkpoint_id"]: h for h in await self.history(run_id, limit=200)}
        current = by_id.get(checkpoint_id)
        while current is not None:
            parent = current["parent_checkpoint_id"]
            current = by_id.get(parent) if parent else None
            if current is not None and frozenset(current["next"]) == nodes:
                return str(current["checkpoint_id"])
        return None

    async def fork(
        self,
        run_id: str,
        checkpoint_id: str,
        *,
        options: Json | None = None,
        title: str | None = None,
        execute: bool = True,
    ) -> RunOutcome:
        """Branch a new run from a checkpoint of ``run_id``, optionally with new run options.

        The new run gets its own run, report and action ids, its own copy of the run's log lines
        and a fresh budget clock; the original run is not touched. With ``execute=False`` the
        fork is only prepared (queued); ``execute(new_run_id)`` continues it.
        """
        snapshot = await self.snapshot(run_id, checkpoint_id)
        if not snapshot.next:
            msg = "this checkpoint is the end of the run; fork from an earlier one"
            raise RunStateError(msg)
        start = frozenset().union(*(FORK_FROM.get(node, frozenset()) for node in snapshot.next))
        if start:
            earlier = await self._ancestor(run_id, checkpoint_id, start)
            if earlier is None:
                msg = f"cannot fork in front of {' and '.join(snapshot.next)}; fork from an earlier step"
                raise RunStateError(msg)
            return await self.fork(run_id, earlier, options=options, title=title, execute=execute)
        stored = snapshot.values.get("request")
        if stored is None:  # the input checkpoint, before the graph has read it
            run = await asyncio.to_thread(repo.get_run, self.engine, run_id)
            stored = (run or {}).get("request")
        if stored is None:
            msg = "this checkpoint holds no request to fork from; fork from a later one"
            raise RunStateError(msg)
        request = TriageRequest.model_validate(stored)
        if options:
            merged = RunOptions.model_validate({**request.options.model_dump(), **options})
            request = request.model_copy(update={"options": merged})
        if title:
            request = request.model_copy(update={"title": title})
        if not snapshot.values.get("plan"):  # nothing has run yet: a fork is simply a new run
            new_id = await asyncio.to_thread(
                self.submit, request, trigger="fork", parent_run_id=run_id
            )
            return await self.execute(new_id) if execute else RunOutcome(new_id, RunStatus.QUEUED)

        new_id = new_run_id()
        request = self._cleaned(request, new_id)  # a new title is as untrusted as any
        await self.checkpointer.acopy_thread(run_id, new_id)
        update = rekey_for_fork(snapshot.values, new_id)
        update["request"] = request.model_dump(mode="json")
        plan = Plan.model_validate(snapshot.values["plan"]).model_copy(
            update={"use_llm": request.options.use_llm, "investigate": request.options.investigate}
        )
        update["plan"] = plan.model_dump(mode="json")
        budget = dict(snapshot.values.get("budget") or {})
        budget.update(started_at=datetime.now(UTC).isoformat(), exhausted=[])
        update["budget"] = Overwrite(budget)
        try:
            forked = await self.graph.aupdate_state(self.config(new_id, checkpoint_id), update)
        except InvalidUpdateError as exc:
            await self.checkpointer.adelete_thread(new_id)
            msg = f"cannot fork at checkpoint {checkpoint_id}: {exc}"
            raise RunStateError(msg) from exc
        await asyncio.to_thread(runlog.copy_run_lines, self.engine, run_id, new_id)
        await asyncio.to_thread(
            repo.create_run,
            self.engine,
            new_id,
            request=request.model_dump(mode="json"),
            trigger="fork",
            title=request.title,
            system=request.system,
            status=RunStatus.QUEUED,
            parent_run_id=run_id,
            forked_from_checkpoint=checkpoint_id,
        )
        await asyncio.to_thread(self._save_forked_report, update, snapshot.values)
        started = {"forked_from": run_id, "checkpoint_id": checkpoint_id}
        if not execute:
            await self._event(new_id, "run_started", payload=started)
            return RunOutcome(new_id, RunStatus.QUEUED)
        return await self._drive(new_id, None, config=forked, started=started)

    async def resend(self, run_id: str, action_id: str, *, by: str) -> OutboundAction:
        """Send an approved message again after it did not go out.

        That is a message whose delivery failed (a webhook was down), or one still marked as
        being sent although no process is sending it (the one that was stopped part way). It
        holds the run as a drive would, so it never races a publish. A message a reviewer never
        approved has no path here, and one that went out is never repeated.
        """
        async with self._holding(run_id):
            if run_id in self.held:  # claimed here for a drive that has yet to start: keep it
                msg = f"run {run_id} is waiting to run; send the message again once it has run"
                raise RunBusyError(msg)
            if not await asyncio.to_thread(
                repo.claim_run, self.engine, run_id, self.owner, status=None
            ):
                msg = f"run {run_id} is running in another process"
                raise RunBusyError(msg)
            try:
                return await self._resend(run_id, action_id, by=by)
            finally:
                await asyncio.to_thread(repo.release_run, self.engine, run_id, self.owner)

    async def _resend(self, run_id: str, action_id: str, *, by: str) -> OutboundAction:
        rows = await asyncio.to_thread(repo.run_actions, self.engine, run_id)
        row = next((r for r in rows if r["id"] == action_id), None)
        if row is None:
            msg = f"run {run_id} has no message {action_id}"
            raise RunNotFoundError(msg)
        if row["status"] not in repo.RESENDABLE:
            msg = (
                "only an approved message that did not go out can be sent again; "
                f"it is {row['status']}"
            )
            raise RunStateError(msg)
        if not await asyncio.to_thread(repo.claim_for_resend, self.engine, action_id):
            msg = f"message {action_id} is being sent again already"
            raise RunBusyError(msg)
        payload = dict(row["payload"] or {})
        action = OutboundAction(
            action_id=action_id,
            kind=row["kind"],
            audience=payload.pop("audience", "responders"),
            evidence_ids=payload.pop("evidence_ids", []),
            title=row["title"],
            body=row["body"],
            payload=payload,
            status="approved",
        )
        settings = self.services.settings
        sent = await send_action(
            action, self.services.config.comms, run_url=run_link(settings, run_id)
        )
        await asyncio.to_thread(repo.save_actions, self.engine, run_id, [sent])
        await self._event(
            run_id,
            "action",
            node="publish",
            payload={"action_id": action_id, "status": sent.status, "resent_by": by},
        )
        return sent

    async def delete(self, run_id: str) -> None:
        """Remove a run everywhere: checkpoints, lines, events, report, actions, audit, memory.

        It holds the run as a drive would, so a review applied at the same moment is refused
        (409) instead of failing halfway and writing checkpoints for a run that is gone."""
        async with self._holding(run_id):
            took = await asyncio.to_thread(
                repo.claim_run, self.engine, run_id, self.owner, status=None
            )
            if not took:
                msg = f"run {run_id} is running in another process"
                raise RunBusyError(msg)
            await self._purge(run_id)
        self._locks.pop(run_id, None)

    async def _purge(self, run_id: str) -> None:
        await self.checkpointer.adelete_thread(run_id)
        for item in await self.store.asearch(("feedback",), filter={"run_id": run_id}, limit=100):
            await self.store.adelete(item.namespace, item.key)

        def purge() -> None:
            with session_scope(self.engine) as session:
                session.execute(
                    delete(LogEventRow).where(
                        LogEventRow.window_id == run_id, LogEventRow.dataset == runlog.RUN_DATASET
                    )
                )
                session.execute(delete(ToolCallRow).where(ToolCallRow.run_id == run_id))
                session.execute(delete(FeedbackRow).where(FeedbackRow.run_id == run_id))
                session.execute(
                    delete(IncidentRow).where(IncidentRow.id == run_incident_id(run_id))
                )
                row = session.get(RunRow, run_id)
                if row is not None:
                    session.delete(row)  # events, reports and actions cascade in the database

        await asyncio.to_thread(purge)
        await self.services.memory.refresh()
        self._last_seq.pop(run_id, None)


def _interrupts(snapshot: StateSnapshot) -> list[Any]:
    return [interrupt.value for task in snapshot.tasks for interrupt in task.interrupts]
