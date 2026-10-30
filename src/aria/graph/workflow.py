"""ARIA's triage workflow as a LangGraph graph.

::

    plan ─▶ parse_shard xN ─▶ merge ─┬─▶ severity ─┐
            (Send fan-out)           └─▶ recall ───┴─▶ investigate ─▶ assess ─▶ report ─▶ comms
                                                         ▲               │
                                                         └──── widen ◀───┘ (replan)
    comms ─▶ review (interrupt) ─┬─▶ publish
                                 └─▶ reject

* ``plan`` sizes the run (shards, budgets, options) and fans parsing out with ``Send``.
* ``merge`` unifies the shards' templates, computes features and stores the run's lines for the
  run-scoped tools.
* ``severity`` and ``recall`` run in parallel, each allocating evidence ids from its own block.
* ``investigate`` runs the ReAct investigator over the MCP tool belt.
* ``assess`` replans when retrieval is weak or no hypothesis is supported: wider retrieval, more
  investigation steps and strict report validation, up to ``plan.max_replans`` times.
* ``review`` pauses with ``interrupt`` until a reviewer approves, edits or rejects the report.
* ``publish`` and ``reject`` are idempotent, so a retry never sends a message twice.

Services travel in the runtime context, never in state. Reviewer feedback and the templates seen
in published runs live in the LangGraph Store, ARIA's long-term memory across runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import weakref
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypedDict

import httpx
from langgraph.cache.base import BaseCache
from langgraph.cache.memory import InMemoryCache
from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore, PutOp
from langgraph.types import (
    CachePolicy,
    Checkpointer,
    Command,
    Overwrite,
    RetryPolicy,
    Send,
    TimeoutPolicy,
    interrupt,
)
from mcp.server.mcpserver import MCPServer
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from aria.agents.investigator import INVESTIGATOR_TOOLS, InvestigationInputs, Investigator
from aria.config import BudgetConfig, Settings
from aria.contracts.base import Claim, EvidenceKind, Severity
from aria.contracts.inputs import TriageRequest
from aria.contracts.parsing import ParsedBatch
from aria.contracts.report import IncidentReport, OutboundAction, ReviewDecision
from aria.contracts.retrieval import Investigation, RetrievalResult
from aria.contracts.run import BudgetUsage, Plan, RunStatus
from aria.contracts.severity import SeverityAssessment, TicketAssessment
from aria.data.loghub import LogRecord, format_raw_line
from aria.db import repository as repo
from aria.db.engine import session_scope
from aria.db.models import LogEventRow
from aria.evidence import EvidenceStore
from aria.graph.state import Json, TriageState, dump_evidence, evidence_of, usage_delta
from aria.llm.budget import BudgetGuard
from aria.llm.router import LLMRouter
from aria.mcp.client import Target, ToolBelt, remote_target
from aria.mcp.server import build_server
from aria.notify import send_action
from aria.parsing.parser import merge_shards, shard_from_payload, shard_to_payload, split_shards
from aria.parsing.parser import parse_shard as parse_shard_lines
from aria.parsing.signals import (
    error_count,
    signal_components,
    signal_templates,
    warning_count,
)
from aria.reporting.comms import AUDIENCE, action_id, draft_comms, is_service_name, redraft
from aria.reporting.composer import SYSTEM_NAMES, ReportContext
from aria.reporting.grounding import validate_report
from aria.reporting.markdown import render_markdown
from aria.reporting.review import apply_review
from aria.reporting.writer import ReportWriter
from aria.retrieval import runlog
from aria.retrieval.memory import MemoryIncident, run_incident_id
from aria.retrieval.retriever import build_query
from aria.security.fields import clean_request
from aria.services import Services
from aria.text import headline

SHARD_LINES = 4_000  # fan parsing out above this many lines
MAX_SHARDS = 8
PARALLEL_BLOCK = 1_000  # evidence ids reserved for each branch that runs alongside another
MAX_ALERT_EVIDENCE = 20
FEEDBACK_REVIEW_THRESHOLD = 2  # corrections that make ARIA ask for a second look
# Without ARIA_PSEUDONYM_KEY: the random key the processes sharing a database keep in it.
_SHARED_KEYS: weakref.WeakKeyDictionary[Engine, bytes] = weakref.WeakKeyDictionary()
TRANSIENT = RetryPolicy(
    max_attempts=3,
    initial_interval=0.25,
    backoff_factor=2.0,
    retry_on=(OperationalError, httpx.TransportError),
)


# --- context -------------------------------------------------------------------------------------


@dataclass
class TriageContext:
    """Per-invocation context: long-lived services, and where the investigator's tools live."""

    services: Services
    tools: Target | None = None
    _server: MCPServer | None = field(default=None, repr=False)

    def tools_target(self) -> Target:
        """A target for one tool belt (remote targets are single-use, so make one per belt)."""
        if self.tools is not None:
            return self.tools
        settings = self.services.settings
        if settings.mcp_url:
            token = settings.mcp_token.get_secret_value() if settings.mcp_token else None
            return remote_target(settings.mcp_url, token)
        if self._server is None:
            self._server = build_server(self.services)
        return self._server


class ShardTask(TypedDict):
    run_id: str
    system: str
    offset: int
    lines: list[str]
    dropped: int


def run_salt(settings: Settings, run_id: str, engine: Engine) -> bytes:
    """The run's pseudonym key: stable across retries, resumes and processes, never in state.

    Without ARIA_PSEUDONYM_KEY, every process sharing the database uses one random key kept in
    it, so the API cleaning an alert and the worker parsing the logs name a host the same way.
    """
    if settings.pseudonym_key:
        key = settings.pseudonym_key.get_secret_value().encode()
    else:
        if engine not in _SHARED_KEYS:
            _SHARED_KEYS[engine] = repo.shared_secret(engine, "pseudonym")
        key = _SHARED_KEYS[engine]
    return hmac.new(key, run_id.encode(), hashlib.sha256).digest()


def run_link(settings: Settings, run_id: str) -> str:
    """Where a message's reader opens the run: the console when its URL is set, else the API."""
    if settings.console_url:
        return f"{settings.console_url.rstrip('/')}/console/runs/{run_id}"
    return f"{settings.public_base_url.rstrip('/')}/api/v1/runs/{run_id}"


def ticket_floor(
    assessment: SeverityAssessment, severity: Severity, priority: str, evidence_id: str
) -> SeverityAssessment:
    """The ticket's own rating as a floor: quiet logs (or none) never rate a ticket below what
    its fields say. Over-triage beats under-triage, and a person confirms either way."""
    claim = Claim(
        text=f"The ticket model rates this priority {priority} ({severity}) from the ticket's "
        f"fields, more severe than the logs alone ({assessment.severity}).",
        evidence_ids=[evidence_id],
    )
    return assessment.model_copy(
        update={
            "severity": severity,
            "floor": severity,
            "prediction_set": [s for s in assessment.prediction_set if s.rank <= severity.rank]
            or [severity],
            "decided_by": "model",
            "auditable": True,
            "needs_review": True,
            "rationale": [claim, *assessment.rationale],
        }
    )


def service_name(request: TriageRequest) -> str:
    """What messages call the affected service: its display name ("HDFS", not "hdfs"), and never
    the "generic" log format's name. A service label that does not read as a name (a sentence,
    a link, markup) is never written into a message: the system's name stands in for it."""
    if request.service and is_service_name(request.service):
        return request.service
    if request.system == "generic":
        return "our service"
    return SYSTEM_NAMES.get(request.system, request.system)


def report_id_for(run_id: str) -> str:
    return f"rpt-{run_id}"


def window_exists(engine: Engine, window_id: str) -> bool:
    """Whether a stored dataset window by this ID has any lines."""
    with session_scope(engine) as session:
        return (
            session.scalar(
                select(LogEventRow.id)
                .where(
                    LogEventRow.window_id == window_id, LogEventRow.dataset != runlog.RUN_DATASET
                )
                .limit(1)
            )
            is not None
        )


def load_window_lines(engine: Engine, window_id: str, system: str) -> list[str]:
    """Re-render a stored dataset window as raw lines for the parser."""
    with session_scope(engine) as session:
        rows = list(
            session.scalars(
                select(LogEventRow)
                .where(
                    LogEventRow.window_id == window_id, LogEventRow.dataset != runlog.RUN_DATASET
                )
                .order_by(LogEventRow.line_no)
            )
        )
    lines = []
    for row in rows:
        fields = {k: v for k, v in (("Component", row.component), ("Level", row.level)) if v}
        record = LogRecord(
            system=row.system or system,
            line_no=row.line_no,
            message=row.message,
            ts=row.ts,
            node=row.node,
            component=row.component,
            level=row.level,
            label=row.label,
            fields=fields,
        )
        lines.append(format_raw_line(record))
    return lines


# --- helpers -------------------------------------------------------------------------------------


def _request(state: TriageState) -> TriageRequest:
    return TriageRequest.model_validate(state["request"])


def _plan(state: TriageState) -> Plan:
    return Plan.model_validate(state.get("plan") or {})


def _limits(services: Services, request: TriageRequest) -> BudgetConfig:
    """The run's budgets: a request may tighten the configured limits, never raise them."""
    limits = services.config.budgets
    overrides = {
        "max_tokens": request.options.max_tokens,
        "max_cost_usd": request.options.max_cost_usd,
    }
    return limits.model_copy(
        update={
            key: min(value, getattr(limits, key))
            for key, value in overrides.items()
            if value is not None
        }
    )


def _guard(state: TriageState, services: Services) -> BudgetGuard:
    usage = BudgetUsage.model_validate(state["budget"]) if state.get("budget") else None
    return BudgetGuard(_limits(services, _request(state)), usage)


def _router(services: Services, request: TriageRequest, plan: Plan) -> LLMRouter | None:
    return services.router.prefer(request.options.provider) if plan.use_llm else None


def _emit(runtime: Runtime[TriageContext], kind: str, node: str, **payload: Any) -> None:
    runtime.stream_writer({"kind": kind, "node": node, "payload": payload})


def _spent(
    runtime: Runtime[TriageContext], node: str, guard: BudgetGuard, before: BudgetUsage
) -> Json:
    """Emit one ``llm_call`` event per call the node made, and return its budget delta."""
    for call in guard.calls:
        _emit(runtime, "llm_call", node, **call)
    return usage_delta(before, guard.usage)


async def _db(fn: Any, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(fn, *args, **kwargs)


# --- plan and parse ------------------------------------------------------------------------------


async def plan(state: TriageState, runtime: Runtime[TriageContext]) -> Command[Any]:
    services = runtime.context.services
    request = _request(state)
    # The runner records the run first; this keeps the graph usable on its own (no-op if present).
    await _db(
        repo.create_run,
        services.engine,
        state["run_id"],
        request=request.model_dump(mode="json"),
        title=request.title,
        system=request.system,
        status=RunStatus.RUNNING,
    )
    lines = list(request.logs)
    if not lines and request.window_id:
        lines = await _db(load_window_lines, services.engine, request.window_id, request.system)
    guard_cfg = services.config.guardrails
    # Alert fields and the title are untrusted too: clean them once, for every node after this.
    salt = await _db(run_salt, services.settings, state["run_id"], services.engine)
    request, withheld = clean_request(request, guard_cfg, salt)
    capped = lines[: guard_cfg.max_lines]
    dropped = max(0, len(lines) - guard_cfg.max_lines)
    shards = 1
    if request.options.fanout and len(capped) > SHARD_LINES:
        shards = min(MAX_SHARDS, math.ceil(len(capped) / SHARD_LINES))
    run_plan = Plan(
        investigate=request.options.investigate,
        use_llm=request.options.use_llm,
        fanout_shards=shards,
        retrieval_k=services.config.retrieval.k,
        retrieval_candidates=services.config.retrieval.candidates,
        notes=[f"{len(lines)} input lines in {shards} {'shard' if shards == 1 else 'shards'}"]
        + (
            [f"{dropped} lines over the {guard_cfg.max_lines}-line limit dropped"]
            if dropped
            else []
        )
        + withheld,
    )
    sends = [
        Send(
            "parse_shard",
            ShardTask(
                run_id=state["run_id"],
                system=request.system,
                offset=offset,
                lines=chunk,
                dropped=dropped if offset == 0 else 0,
            ),
        )
        for offset, chunk in split_shards(capped, shards)
    ]
    usage = BudgetUsage()  # the run's clock starts here
    return Command(
        update={
            "request": request.model_dump(mode="json"),
            "plan": run_plan.model_dump(mode="json"),
            "status": str(RunStatus.RUNNING),
            "budget": usage.model_dump(mode="json"),
            "notes": run_plan.notes,
        },
        goto=sends,
    )


def parse_shard(task: ShardTask, runtime: Runtime[TriageContext]) -> Json:
    services = runtime.context.services
    result = parse_shard_lines(
        task["lines"],
        system=task["system"],
        offset=task["offset"],
        guard=services.config.guardrails,
        salt=run_salt(services.settings, task["run_id"], services.engine),
        dropped=task["dropped"],
    )
    return {"shards": [shard_to_payload(result)]}


async def _known_templates(store: BaseStore | None, system: str) -> list[str]:
    if store is None:
        return []
    items = await store.asearch(("templates", system), limit=20_000)
    return [str(item.value["template"]) for item in items if "template" in item.value]


def _alert_evidence(request: TriageRequest, evidence: EvidenceStore) -> list[str]:
    """Alerts as evidence. ``plan`` has already cleaned them (``security.fields``)."""
    notes: list[str] = []
    for alert in request.alerts[:MAX_ALERT_EVIDENCE]:
        parts = {
            "name": alert.name,
            "status": alert.status,
            "severity": alert.labels.get("severity", ""),
            "service": alert.labels.get("service", ""),
        }
        evidence.add(
            EvidenceKind.ALERT,
            f"Alert {parts['name']} ({parts['status']}) from {alert.source}",
            source=f"alert.{alert.source}",
            detail=", ".join(f"{k}={v}" for k, v in parts.items() if v),
            data={**parts, "fingerprint": alert.fingerprint, "source": alert.source},
            ts=alert.starts_at,
        )
    return notes


async def merge(state: TriageState, runtime: Runtime[TriageContext]) -> Json:
    services = runtime.context.services
    request = _request(state)
    run_plan = _plan(state)
    shards = sorted(
        (shard_from_payload(payload) for payload in state.get("shards", [])),
        key=lambda shard: shard.offset,
    )
    evidence = EvidenceStore(evidence_of(state))
    known = await _known_templates(runtime.store, request.system)
    n_raw = sum(len(s.lines) for s in shards) + sum(s.dropped for s in shards)
    out = merge_shards(
        shards,
        system=request.system,
        evidence=evidence,
        known_templates=known,
        context_lines=run_plan.context_lines,
        n_raw_lines=n_raw,
    )
    await _db(runlog.store_run_lines, services.engine, state["run_id"], request.system, out.lines)
    notes = _alert_evidence(request, evidence)
    injections = len(out.batch.guard.injections)
    if injections:
        notes.append(
            f"{injections} line(s) quarantined as possible prompt injection; they are shown to "
            "reviewers but excluded from analysis and tools"
        )
        _emit(runtime, "guardrail", "merge", quarantined=injections)
    if request.synthetic:
        notes.append("input is a semi-synthetic scenario built from real Loghub lines")
    return {
        "batch": out.batch.model_dump(mode="json"),
        "evidence": dump_evidence(evidence.new_items()),
        "shards": Overwrite([]),
        "notes": notes,
    }


# --- severity and retrieval (parallel) -----------------------------------------------------------


async def _reviewer_corrections(
    store: BaseStore | None, system: str, severity: Severity
) -> list[Json]:
    """Earlier reviews on this system that changed a severity like this one, most recent first."""
    if store is None:
        return []
    items = await store.asearch(("feedback", system), filter={"from": str(severity)}, limit=50)
    return [item.value for item in items if item.value.get("to") not in (None, str(severity))]


async def severity(state: TriageState, runtime: Runtime[TriageContext]) -> Json:
    services = runtime.context.services
    request, run_plan = _request(state), _plan(state)
    batch = ParsedBatch.model_validate(state["batch"])
    evidence = EvidenceStore(evidence_of(state))
    guard = _guard(state, services)
    before = guard.snapshot()
    result = await services.severity.assess(
        batch.features,
        system=request.system,
        evidence=evidence,
        alerts=request.alerts,
        router=_router(services, request, run_plan),
        budget=guard,
        use_llm=run_plan.use_llm,
    )
    assessment = result.assessment
    notes: list[str] = []

    ticket: TicketAssessment | None = None
    if request.ticket is not None and services.tickets is not None:
        prediction = services.tickets.predict(request.ticket)
        eid = evidence.add(
            EvidenceKind.MODEL,
            f"Ticket model: priority {prediction.priority} ({prediction.severity})",
            source="severity.ticket_model",
            detail=f"prediction set {prediction.prediction_set}; "
            f"SLA breach risk {prediction.sla_breach_risk}",
            data={
                "priority": prediction.priority,
                "severity": str(prediction.severity),
                "probabilities": prediction.probabilities,
                "sla_breach_risk": prediction.sla_breach_risk,
                "matrix_priority": prediction.matrix_priority,
                "model_priority": prediction.model_priority,
                "decided_by": prediction.decided_by,
                "model_version": services.tickets.version,
            },
        )
        ticket = TicketAssessment(
            predicted_priority=prediction.priority,
            severity=prediction.severity,
            probabilities=prediction.probabilities,
            prediction_set=prediction.prediction_set,
            sla_breach_risk=prediction.sla_breach_risk,
            evidence_ids=[eid],
            model_version=services.tickets.version,
        )
        if prediction.severity.rank < assessment.severity.rank:
            notes.append(
                f"the ticket model rates this {prediction.severity}, more severe than the "
                f"log-based {assessment.severity}; ARIA takes the more severe and asks for review"
            )
            assessment = ticket_floor(assessment, prediction.severity, prediction.priority, eid)

    corrections = await _reviewer_corrections(runtime.store, request.system, assessment.severity)
    if corrections:
        targets = sorted({str(c["to"]) for c in corrections})
        evidence.add(
            EvidenceKind.FEEDBACK,
            f"Reviewers changed {assessment.severity} to {', '.join(targets)} in "
            f"{len(corrections)} earlier run(s) on {request.system}",
            source="memory.feedback",
            detail="; ".join(
                f"{c.get('run_id')}: {c.get('from')} -> {c.get('to')} ({c.get('failure_mode')})"
                for c in corrections[:10]
            ),
            data={"corrections": len(corrections), "to": targets},
        )
        if len(corrections) >= FEEDBACK_REVIEW_THRESHOLD and not assessment.needs_review:
            assessment = assessment.model_copy(update={"needs_review": True})
            notes.append("reviewers have corrected similar ratings before; flagged for review")

    return {
        "severity": assessment.model_dump(mode="json"),
        "ticket": ticket.model_dump(mode="json") if ticket else None,
        "evidence": dump_evidence(evidence.new_items()),
        "budget": _spent(runtime, "severity", guard, before),
        "notes": notes,
    }


async def _retrieve(
    state: TriageState, runtime: Runtime[TriageContext], *, node: str, parallel: bool
) -> Json:
    services = runtime.context.services
    request, run_plan = _request(state), _plan(state)
    batch = ParsedBatch.model_validate(state["batch"])
    base = EvidenceStore(evidence_of(state))
    start = base.next_id + PARALLEL_BLOCK if parallel else None
    evidence = EvidenceStore(base.all(), start=start)
    guard = _guard(state, services)
    before = guard.snapshot()
    hypotheses = []
    if state.get("investigation"):
        hypotheses = Investigation.model_validate(state["investigation"]).hypotheses
    result = await services.retriever.retrieve(
        build_query(batch, hypotheses),
        evidence=evidence,
        ticket=request.ticket,
        k=run_plan.retrieval_k,
        candidates=run_plan.retrieval_candidates,
        widen_level=run_plan.widen_level,
        budget=guard,
        use_llm=run_plan.use_llm,
    )
    return {
        "retrieval": result.model_dump(mode="json"),
        "evidence": dump_evidence(evidence.new_items()),
        "budget": _spent(runtime, node, guard, before),
    }


async def recall(state: TriageState, runtime: Runtime[TriageContext]) -> Json:
    return await _retrieve(state, runtime, node="recall", parallel=True)


async def widen(state: TriageState, runtime: Runtime[TriageContext]) -> Json:
    return await _retrieve(state, runtime, node="widen", parallel=False)


# --- investigation and replanning ----------------------------------------------------------------


async def investigate(state: TriageState, runtime: Runtime[TriageContext]) -> Json:
    services = runtime.context.services
    request, run_plan = _request(state), _plan(state)
    if not run_plan.investigate:
        skipped = Investigation(stopped_reason="disabled")
        return {"investigation": skipped.model_dump(mode="json")}
    batch = ParsedBatch.model_validate(state["batch"])
    assessment = SeverityAssessment.model_validate(state["severity"])
    retrieval = RetrievalResult.model_validate(state.get("retrieval") or {})
    evidence = EvidenceStore(evidence_of(state))
    guard = _guard(state, services)
    before = guard.snapshot()
    config = services.config.investigation
    # The LLM chooses the tools on the first pass; replans add steps but run the
    # deterministic policy, so a hard incident cannot spend the whole budget investigating.
    router = _router(services, request, run_plan) if run_plan.replans == 0 else None
    investigator = Investigator(
        router,
        max_steps=config.max_steps + 2 * run_plan.replans,  # a replan buys more steps
        max_hypotheses=config.max_hypotheses,
        max_rounds=config.max_rounds,
        max_parallel=config.max_parallel,
    )
    belt = ToolBelt(
        runtime.context.tools_target(),
        allowed=INVESTIGATOR_TOOLS,
        agent="investigator",
        run_id=state["run_id"],
        evidence=evidence,
        budget=guard,
    )
    inputs = InvestigationInputs(
        run_id=state["run_id"],
        system=request.system,
        batch=batch,
        severity=assessment,
        similar=retrieval.incidents,
        runbooks=retrieval.runbooks,
    )
    async with belt:
        result = await investigator.run(
            inputs,
            belt,
            evidence,
            budget=guard,
            emit=lambda kind, payload: _emit(runtime, kind, "investigate", **payload),
        )
    await _db(repo.save_tool_calls, services.engine, state["run_id"], belt.records)
    return {
        "investigation": result.model_dump(mode="json"),
        "evidence": dump_evidence(evidence.new_items()),
        "tool_calls": [record.model_dump(mode="json") for record in belt.records],
        "budget": _spent(runtime, "investigate", guard, before),
    }


def assess(state: TriageState, runtime: Runtime[TriageContext]) -> Command[Any]:
    services = runtime.context.services
    run_plan = _plan(state)
    retrieval = RetrievalResult.model_validate(state.get("retrieval") or {})
    investigation = Investigation.model_validate(state.get("investigation") or {})
    usage = BudgetUsage.model_validate(state.get("budget") or {})
    reasons = []
    min_grade = services.config.retrieval.min_grade
    if retrieval.grade < min_grade:
        reasons.append(
            f"similar-incident match is weak (grade {retrieval.grade:.2f} < {min_grade})"
        )
    if run_plan.investigate and investigation.leading_hypothesis is None:
        reasons.append("no hypothesis is supported yet")
    if reasons and not signal_templates(ParsedBatch.model_validate(state["batch"])):
        # No errors and no new warnings: there is no problem to explain, and a wider search
        # cannot find a cause for one. Say so instead of replanning.
        note = "no errors or new warnings in the window, so ARIA did not replan"
        return Command(update={"replan_reasons": [*reasons, note]}, goto="report")
    can_replan = (
        run_plan.replans < run_plan.max_replans and run_plan.widen_level < 3 and not usage.exhausted
    )
    if reasons and can_replan:
        count = run_plan.replans + 1
        note = f"replan {count}: " + "; ".join(reasons)
        new_plan = run_plan.model_copy(
            update={
                "replans": count,
                "widen_level": run_plan.widen_level + 1,
                "retrieval_candidates": min(
                    services.config.retrieval.widen_candidates, run_plan.retrieval_candidates * 2
                ),
                "validation": "strict",
                "notes": [*run_plan.notes, note],
            }
        )
        _emit(runtime, "replan", "assess", replans=count, reasons=reasons)
        return Command(
            update={
                "plan": new_plan.model_dump(mode="json"),
                "replan_reasons": reasons,
                "notes": [note],
            },
            goto="widen",
        )
    if reasons:
        reasons = [*reasons, "no replans left; continuing with what ARIA has"]
    return Command(update={"replan_reasons": reasons}, goto="report")


# --- report and comms ----------------------------------------------------------------------------


def _report_context(state: TriageState, services: Services) -> ReportContext:
    request = _request(state)
    return ReportContext(
        run_id=state["run_id"],
        system=request.system,
        batch=ParsedBatch.model_validate(state["batch"]),
        severity=SeverityAssessment.model_validate(state["severity"]),
        evidence=evidence_of(state),
        retrieval=RetrievalResult.model_validate(state.get("retrieval") or {}),
        investigation=Investigation.model_validate(state.get("investigation") or {}),
        alerts=list(request.alerts),
        runbooks=services.runbooks,
        service=request.service,
        title_hint=request.title,
    )


async def report(state: TriageState, runtime: Runtime[TriageContext]) -> Json:
    services = runtime.context.services
    request, run_plan = _request(state), _plan(state)
    ctx = _report_context(state, services)
    guard = _guard(state, services)
    before = guard.snapshot()
    writer = ReportWriter(
        _router(services, request, run_plan),
        services.runbooks,
        safety_check=services.config.guardrails.safety_model,
    )
    outcome = await writer.write(
        ctx,
        report_id=report_id_for(state["run_id"]),
        use_llm=run_plan.use_llm,
        validation=run_plan.validation,
        budget=guard,
        on_token=lambda text: _emit(runtime, "token", "report", text=text),
        on_reset=lambda: _emit(runtime, "token", "report", reset=True),
    )
    incident = outcome.report
    markdown = render_markdown(incident, decided_by=ctx.severity.decided_by)
    await _db(repo.save_report, services.engine, incident, markdown=markdown)
    meta = {
        "llm_used": outcome.llm_used,
        "provider": outcome.provider,
        "model": outcome.model,
        "critic": outcome.critic,
        "removed_claims": outcome.removed_claims,
        "fell_back": outcome.fell_back,
        "safety": outcome.safety,
        "validation": run_plan.validation,
    }
    return {
        "report": incident.model_dump(mode="json"),
        "report_meta": meta,
        "budget": _spent(runtime, "report", guard, before),
        "notes": outcome.notes,
    }


async def comms(state: TriageState, runtime: Runtime[TriageContext]) -> Json:
    services = runtime.context.services
    request, run_plan = _request(state), _plan(state)
    incident = IncidentReport.model_validate(state["report"])
    guard = _guard(state, services)
    before = guard.snapshot()
    outcome = await draft_comms(
        incident,
        service=service_name(request),
        run_url=run_link(services.settings, state["run_id"]),
        router=_router(services, request, run_plan),
        budget=guard,
        use_llm=run_plan.use_llm,
        safety_check=services.config.guardrails.safety_model,
    )
    await _db(repo.save_actions, services.engine, state["run_id"], outcome.actions)
    notes = [
        f"comms draft for {key} dropped: {'; '.join(p)}" for key, p in outcome.rejected.items()
    ]
    return {
        "actions": [action.model_dump(mode="json") for action in outcome.actions],
        "budget": _spent(runtime, "comms", guard, before),
        "notes": notes,
    }


# --- review and publication ----------------------------------------------------------------------


def review_payload(state: TriageState) -> Json:
    incident = IncidentReport.model_validate(state["report"])
    assessment = SeverityAssessment.model_validate(state["severity"])
    return {
        "type": "review",
        "run_id": state["run_id"],
        "report_id": incident.report_id,
        "title": incident.title,
        "severity": str(incident.severity),
        "decided_by": assessment.decided_by,
        "confidence": assessment.confidence,
        "needs_review": assessment.needs_review,
        "prediction_set": [str(s) for s in assessment.prediction_set],
        "valid": incident.validation.ok,
        "generated_by": incident.generated_by,
        "actions": [
            {k: a[k] for k in ("action_id", "kind", "audience", "title")}
            for a in state.get("actions", [])
        ],
        "decisions": ["approve", "edit", "reject"],
    }


def review(state: TriageState, runtime: Runtime[TriageContext]) -> Command[Any]:
    settings = runtime.context.services.settings
    request = _request(state)
    if not settings.require_approval and not request.options.require_approval:
        # Unattended runs publish the report but never send anything outbound.
        decision = ReviewDecision(
            decision="approve", reviewer="aria:auto", comment="approval not required for this run"
        )
        return Command(update={"review": decision.model_dump(mode="json")}, goto="publish")
    payload = review_payload(state)
    known = {a["action_id"] for a in state.get("actions", [])}
    error: str | None = None
    while True:
        # Everything before interrupt() re-runs on resume, so nothing above has side effects.
        answer = interrupt({**payload, "error": error} if error else payload)
        try:
            decision = ReviewDecision.model_validate(answer)
            unknown = sorted(set(decision.approve_actions) - known)
            if unknown:
                error = f"unknown action ids: {', '.join(unknown)}"
                continue
            if decision.decision == "edit" and decision.edits is None:
                error = "an edit decision needs edits"
                continue
            break
        except ValidationError as exc:
            error = "; ".join(e["msg"] for e in exc.errors(include_url=False))[:500]
    goto = "reject" if decision.decision == "reject" else "publish"
    return Command(update={"review": decision.model_dump(mode="json")}, goto=goto)


def _memory_incident(
    state: TriageState, incident: IncidentReport, assessment: SeverityAssessment, synthetic: bool
) -> MemoryIncident:
    request = _request(state)
    batch = ParsedBatch.model_validate(state["batch"])
    investigation = Investigation.model_validate(state.get("investigation") or {})
    retrieval = RetrievalResult.model_validate(state.get("retrieval") or {})
    leading = next(
        (h for h in investigation.hypotheses if h.id == investigation.leading_hypothesis), None
    )
    # Without a lead, only a past incident that applies here may lend its cause to memory.
    analogue = next(
        (
            i.failure_mode
            for i in retrieval.incidents[:1]
            if i.applies_to(request.system, batch.features.components)
        ),
        "unknown",
    )
    failure_mode = leading.failure_mode if leading else analogue
    errors = [t.template for t in batch.templates if t.error_like][:3]
    runbook = next((a.runbook_slug for a in incident.actions if a.runbook_slug), None)
    resolution = "; ".join(a.text for a in incident.actions[:3]) or "See the published report."
    return MemoryIncident(
        id=run_incident_id(state["run_id"]),
        title=headline(incident.title),  # its severity has a field of its own
        system=request.system,
        failure_mode=failure_mode,
        severity=assessment.severity,
        summary=" ".join(claim.text for claim in incident.summary)[:2_000],
        resolution=resolution[:2_000],
        signature=" | ".join(errors),
        components=signal_components(batch, 8) or batch.features.components[:8],
        runbook_slug=runbook,
        first_seen=batch.templates[0].first_ts if batch.templates else None,
        last_seen=datetime.now(UTC),
        affected_nodes=batch.features.error_nodes,
        source="run",
        synthetic=synthetic,
        report_id=incident.report_id,
    )


async def _remember_templates(store: BaseStore | None, batch: ParsedBatch) -> None:
    """Teach the template history what normal traffic looks like: the run's routine templates.

    Templates with error or warning lines stay out, so the same incident still stands out as
    new when it recurs; incident memory is what recognises a recurrence.
    """
    routine = [t for t in batch.templates if not error_count(t) and not warning_count(t)]
    if store is None or not routine:
        return
    await store.abatch(
        [
            PutOp(
                ("templates", batch.system),
                t.template_id,
                {"template": t.template, "count": t.count, "error_like": False},
            )
            for t in routine
        ]
    )


async def _record_feedback(
    state: TriageState,
    runtime: Runtime[TriageContext],
    *,
    decision: ReviewDecision,
    original: SeverityAssessment,
    final: Severity,
    failure_mode: str,
) -> None:
    services = runtime.context.services
    request = _request(state)
    value = {
        "run_id": state["run_id"],
        "decision": decision.decision,
        "from": str(original.severity),
        "to": str(final),
        "rule_severity": str(original.rule_severity),
        "decided_by": original.decided_by,
        "failure_mode": failure_mode,
        "reviewer": decision.reviewer,
        "comment": decision.comment,
    }
    # The database copy also keeps the run's model input, so reviews can recalibrate the model.
    batch = ParsedBatch.model_validate(state["batch"])
    model_row = services.severity.model_row(batch.features, request.alerts)
    await _db(
        repo.save_feedback,
        services.engine,
        state["run_id"],
        "review",
        {**value, "model_row": model_row, "model_version": original.model_version},
        author=decision.reviewer,
        comment=decision.comment,
    )
    if runtime.store is not None:
        await runtime.store.aput(("feedback", request.system, failure_mode), state["run_id"], value)


async def publish(state: TriageState, runtime: Runtime[TriageContext]) -> Json:
    services = runtime.context.services
    request = _request(state)
    run_id = state["run_id"]
    decision = ReviewDecision.model_validate(state["review"])
    original = SeverityAssessment.model_validate(state["severity"])
    evidence = EvidenceStore(evidence_of(state))
    drafted = IncidentReport.model_validate(state["report"])
    incident, assessment = apply_review(drafted, original, decision, evidence)
    validation = validate_report(
        incident,
        evidence=evidence.all(),
        expected_severity=assessment.severity,
        runbooks=services.runbooks,
        strict=_plan(state).validation == "strict",
    )
    incident = incident.model_copy(update={"status": "published", "validation": validation})
    markdown = render_markdown(incident, decided_by=assessment.decided_by)
    await _db(
        repo.save_report,
        services.engine,
        incident,
        markdown=markdown,
        reviewer=decision.reviewer,
        comment=decision.comment,
    )
    memory = _memory_incident(state, incident, assessment, request.synthetic)
    await services.memory.remember(memory)

    approved = set(decision.approve_actions)
    already = await _db(repo.action_statuses, services.engine, run_id)
    run_url = run_link(services.settings, run_id)
    proposed = [OutboundAction.model_validate(raw) for raw in state.get("actions", [])]
    if (incident.title, incident.severity) != (drafted.title, drafted.severity):
        proposed = redraft(proposed, incident, service=service_name(request), run_url=run_url)
    actions: list[OutboundAction] = []
    for proposal in proposed:
        if proposal.action_id not in approved:
            action = proposal.model_copy(update={"status": "rejected"})
        elif already.get(proposal.action_id) == "sent":
            action = proposal.model_copy(update={"status": "sent"})
        elif not await _db(repo.claim_action, services.engine, run_id, proposal):
            # Another drive of this run took it first. Run claims should make that impossible;
            # this keeps a message from going out twice even if they fail.
            actions.append(proposal.model_copy(update={"status": "approved"}))
            continue
        else:
            action = await send_action(
                proposal.model_copy(update={"status": "approved"}),
                services.config.comms,
                run_url=run_url,
            )
            _emit(runtime, "action", "publish", action_id=action.action_id, status=action.status)
        # Save each action as soon as it is settled, so a retry sees what was already sent.
        await _db(
            repo.save_actions, services.engine, run_id, [action], approved_by=decision.reviewer
        )
        actions.append(action)

    batch = ParsedBatch.model_validate(state["batch"])
    await _remember_templates(runtime.store, batch)
    if decision.reviewer != "aria:auto":
        await _record_feedback(
            state,
            runtime,
            decision=decision,
            original=original,
            final=assessment.severity,
            failure_mode=memory.failure_mode,
        )
    _emit(runtime, "review", "publish", decision=decision.decision, reviewer=decision.reviewer)
    return {
        "report": incident.model_dump(mode="json"),
        "severity": assessment.model_dump(mode="json"),
        "actions": [action.model_dump(mode="json") for action in actions],
        "evidence": dump_evidence(evidence.new_items()),
        "status": str(RunStatus.PUBLISHED),
    }


async def reject(state: TriageState, runtime: Runtime[TriageContext]) -> Json:
    services = runtime.context.services
    run_id = state["run_id"]
    decision = ReviewDecision.model_validate(state["review"])
    original = SeverityAssessment.model_validate(state["severity"])
    evidence = EvidenceStore(evidence_of(state))
    incident, _ = apply_review(
        IncidentReport.model_validate(state["report"]), original, decision, evidence
    )
    incident = incident.model_copy(update={"status": "rejected"})
    markdown = render_markdown(incident, decided_by=original.decided_by)
    await _db(
        repo.save_report,
        services.engine,
        incident,
        markdown=markdown,
        reviewer=decision.reviewer,
        comment=decision.comment,
    )
    actions = [
        OutboundAction.model_validate(raw).model_copy(update={"status": "rejected"})
        for raw in state.get("actions", [])
    ]
    await _db(repo.save_actions, services.engine, run_id, actions, approved_by=decision.reviewer)
    investigation = Investigation.model_validate(state.get("investigation") or {})
    leading = next(
        (h for h in investigation.hypotheses if h.id == investigation.leading_hypothesis), None
    )
    await _record_feedback(
        state,
        runtime,
        decision=decision,
        original=original,
        final=original.severity,
        failure_mode=leading.failure_mode if leading else "unknown",
    )
    _emit(runtime, "review", "reject", decision="reject", reviewer=decision.reviewer)
    return {
        "report": incident.model_dump(mode="json"),
        "actions": [action.model_dump(mode="json") for action in actions],
        "evidence": dump_evidence(evidence.new_items()),
        "status": str(RunStatus.REJECTED),
    }


# --- failures and assembly -----------------------------------------------------------------------


def on_node_error(_state: TriageState, error: NodeError) -> Command[Any]:
    """Any node that still fails after its retries ends the run as failed, with the reason."""
    message = f"{type(error.error).__name__}: {error.error}"[:1_000]
    return Command(
        update={
            "status": str(RunStatus.FAILED),
            "errors": [{"node": error.node, "error": message}],
        },
        goto=END,
    )


def build_graph(
    *,
    checkpointer: Checkpointer = None,
    store: BaseStore | None = None,
    cache: BaseCache[Any] | None = None,
) -> CompiledStateGraph[TriageState, TriageContext, TriageState, TriageState]:
    builder = StateGraph(TriageState, context_schema=TriageContext)
    # LangGraph injects NodeError into handlers by annotation; its stubs don't list that shape.
    builder.set_node_defaults(retry_policy=TRANSIENT, error_handler=on_node_error)  # type: ignore[arg-type]
    llm_timeout = TimeoutPolicy(run_timeout=300, idle_timeout=120)
    builder.add_node("plan", plan, destinations=("parse_shard",))
    builder.add_node(  # type: ignore[call-overload]  # stubs reject TypedDict input schemas
        "parse_shard",
        parse_shard,
        input_schema=ShardTask,
        cache_policy=CachePolicy(ttl=3_600),
    )
    builder.add_node("merge", merge, timeout=120)
    builder.add_node("severity", severity, timeout=llm_timeout)
    builder.add_node("recall", recall, timeout=llm_timeout)
    builder.add_node(
        "investigate", investigate, timeout=TimeoutPolicy(run_timeout=600, idle_timeout=180)
    )
    builder.add_node("assess", assess, destinations=("widen", "report"))
    builder.add_node("widen", widen, timeout=llm_timeout)
    builder.add_node("report", report, timeout=llm_timeout)
    builder.add_node("comms", comms, timeout=llm_timeout)
    builder.add_node("review", review, destinations=("publish", "reject"))
    builder.add_node("publish", publish, timeout=120)
    builder.add_node("reject", reject, timeout=60)

    builder.add_edge(START, "plan")
    builder.add_edge("parse_shard", "merge")
    builder.add_edge("merge", "severity")
    builder.add_edge("merge", "recall")
    builder.add_edge(["severity", "recall"], "investigate")
    builder.add_edge("widen", "investigate")
    builder.add_edge("investigate", "assess")
    builder.add_edge("report", "comms")
    builder.add_edge("comms", "review")
    builder.add_edge("publish", END)
    builder.add_edge("reject", END)
    return builder.compile(
        checkpointer=checkpointer,
        store=store,
        cache=cache or InMemoryCache(),
        name="aria-triage",
    )


def rekey_for_fork(values: Json, run_id: str) -> Json:
    """State updates that give a forked run its own run, report and action ids.

    Without them the fork would publish over the original run's report and actions.
    """
    update: Json = {"run_id": run_id}
    rid = report_id_for(run_id)
    if values.get("report"):
        update["report"] = {**values["report"], "run_id": run_id, "report_id": rid}
    if values.get("actions"):
        keys = {audience: key for key, audience in AUDIENCE.items()}
        update["actions"] = [
            {
                **raw,
                "action_id": action_id(rid, keys.get(raw.get("audience", ""), raw["kind"])),
                "status": "proposed",
                "result": {},
            }
            for raw in values["actions"]
        ]
    return update
