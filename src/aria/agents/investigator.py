"""The investigator: a bounded ReAct loop that tests hypotheses with read-only MCP tools.

Each step, the investigator (an LLM, or a deterministic policy when none is configured):

1. adds hypotheses (failure mode + component) when it has none;
2. updates them with the evidence it has gathered;
3. calls one allowlisted, read-only tool, or finishes.

Guard rails: the tool belt refuses anything off the allowlist and pins run-scoped tools to the
current run, so the model cannot read other runs; every step and tool call is budgeted; an
update may only cite evidence that exists. When the loop ends, each hypothesis becomes citable
evidence for the report.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from aria.contracts.base import Claim, Evidence, EvidenceKind
from aria.contracts.parsing import BrokenUnit, ParsedBatch
from aria.contracts.retrieval import Hypothesis, Investigation, RunbookRef, SimilarIncident
from aria.contracts.severity import SeverityAssessment
from aria.evidence import EvidenceStore
from aria.llm.base import BudgetExceededError, LLMError
from aria.llm.budget import BudgetGuard
from aria.llm.jsonschema import restrict_enum, strict_schema
from aria.llm.prompts import build_messages
from aria.llm.router import LLMRouter
from aria.llm.schemas import (
    HypothesisUpdate,
    InvestigatorStep,
    NewHypothesis,
    ToolArguments,
    ToolRequest,
)
from aria.mcp.client import ToolBelt, ToolNotAllowedError
from aria.parsing.flows import load_flow_settings
from aria.parsing.signals import signal_components, signal_templates
from aria.text import clip

INVESTIGATOR_TOOLS = (
    "search_logs",
    "get_template_examples",
    "component_timeline",
    "node_breakdown",
    "search_incidents",
    "get_runbook",
)
_WORDS = re.compile(r"[a-z][a-z0-9_]{2,}")
GENERIC_CAUSE = "component_errors"  # "<component> is failing": the window's own signal
LIFECYCLE_CAUSE = "unfinished_work"  # units of work that stop partway (parsing/flows.py)
Emit = Callable[[str, dict[str, Any]], None]
Mode = Literal["auto", "llm", "deterministic"]


@dataclass
class InvestigationInputs:
    run_id: str
    system: str
    batch: ParsedBatch
    severity: SeverityAssessment
    similar: list[SimilarIncident] = field(default_factory=list)
    runbooks: list[RunbookRef] = field(default_factory=list)


@dataclass
class Observation:
    tool: str
    arguments: dict[str, Any]
    ok: bool
    summary: str
    evidence_ids: list[str]
    data: dict[str, Any] | None = None

    def brief(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "ok": self.ok,
            "summary": self.summary[:300],
            "evidence_ids": self.evidence_ids,
        }


@dataclass
class _Loop:
    inputs: InvestigationInputs
    belt: ToolBelt
    evidence: EvidenceStore
    budget: BudgetGuard | None
    plan: list[dict[str, Any]]
    hypotheses: list[Hypothesis] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    touched: set[str] = field(default_factory=set)  # hypotheses the LLM has updated


def _top_component(batch: ParsedBatch) -> str | None:
    """Where the signal is: a critical component logging errors, else the component of the
    strongest error or new-warning template; None for a window without either. Templates leave
    out quarantined lines, which are shown to reviewers but must never steer the investigation."""
    components = signal_components(batch, 1)
    return components[0] if components else None


def _ran(loop: _Loop, tool: str, arguments: dict[str, Any]) -> bool:
    """Has this call run already? Compared as the belt sends it: filtered and pinned to the run."""
    wanted = loop.belt.prepared(tool, arguments)
    return any(o.tool == tool and o.arguments == wanted for o in loop.observations)


def _component_for(
    incident: SimilarIncident, batch: ParsedBatch, fallback: str | None
) -> str | None:
    """The component to test a past incident's cause on: where that incident's signal was, if
    that component carries signal here too; else one of its components present here (a quiet
    timeline then counts against it); else the window's top component."""
    signal = signal_components(batch)
    present = set(batch.features.components)
    return next(
        (c for c in signal if c in incident.components),
        next((c for c in incident.components if c in present), fallback),
    )


def _broken_units(batch: ParsedBatch) -> list[BrokenUnit]:
    """Units of work the parser saw stop partway, of the kind with the most of them."""
    examples = batch.flows.examples
    if not examples:
        return []
    kind = max(batch.flows.checked, key=lambda k: sum(1 for e in examples if e.kind == k))
    return [e for e in examples if e.kind == kind]


def _lifecycle_hypothesis(batch: ParsedBatch) -> NewHypothesis | None:
    """Work that started but never finished: the cause to test when a window logs no error."""
    broken = _broken_units(batch)
    if not broken:
        return None
    kind = broken[0].kind
    missing = next((e.steps[-1] for e in broken if e.problem == "mismatch" and e.steps), None)
    template = next((t for t in batch.templates if t.template_id == missing), None)
    component = template.components[0] if template is not None and template.components else None
    n = sum(1 for e in batch.flows.examples if e.kind == kind)
    count = batch.flows.broken if n == len(batch.flows.examples) else n
    return NewHypothesis(
        statement=(
            f"Work on {kind}s stops partway: {count} of {batch.flows.checked.get(kind, 0)} "
            "never finished every step, with no error logged"
        ),
        failure_mode=LIFECYCLE_CAUSE,
        component=component,
    )


def _is_unit_key(query: str) -> bool:
    return any(kind.pattern.search(query) for kind in load_flow_settings().kinds)


def candidate_hypotheses(inputs: InvestigationInputs, *, limit: int = 3) -> list[NewHypothesis]:
    """Plausible causes to test: work the parser saw stop partway, similar incidents, and the
    window's own signal."""
    batch = inputs.batch
    component = _top_component(batch)
    seen: set[str] = set()
    out: list[NewHypothesis] = []
    lifecycle = _lifecycle_hypothesis(batch)
    if lifecycle is not None:
        seen.add(LIFECYCLE_CAUSE)
        out.append(lifecycle)
    for incident in inputs.similar:
        if incident.failure_mode in seen or incident.failure_mode == "none":
            continue
        # Another system's incident with nothing in common is no cause to test: every generic
        # check (example lines, a busy timeline) would seem to bear it out.
        if not incident.applies_to(inputs.system, batch.features.components):
            continue
        seen.add(incident.failure_mode)
        label = incident.failure_mode.replace("_", " ")
        out.append(
            NewHypothesis(
                statement=f"{label.capitalize()}, as in past incident {incident.incident_id}",
                failure_mode=incident.failure_mode,
                component=_component_for(incident, batch, component),
            )
        )
    signal = signal_templates(batch)
    if signal and component and GENERIC_CAUSE not in seen:
        top = signal[0]
        where = top.components[0] if top.components else component
        out.append(
            NewHypothesis(
                statement=f'{where} is failing: "{clip(top.template, 80)}" repeats {top.count} times',
                failure_mode=GENERIC_CAUSE,
                component=where,
            )
        )
    return out[:limit]


def suggested_plan(inputs: InvestigationInputs) -> list[dict[str, Any]]:
    """A sensible default sequence of tool calls; the LLM may deviate within the allowlist."""
    signal = signal_templates(inputs.batch)
    component = _top_component(inputs.batch)
    # Read the whole life of two units that stopped partway, from the run's own lines.
    plan: list[dict[str, Any]] = [
        {"tool": "search_logs", "arguments": {"query": unit.key, "limit": 20}}
        for unit in _broken_units(inputs.batch)[:2]
    ]
    lifecycle_runbook = next(
        (r.slug for r in inputs.runbooks if LIFECYCLE_CAUSE in r.failure_modes), None
    )
    if lifecycle_runbook and _broken_units(inputs.batch):
        plan.append({"tool": "get_runbook", "arguments": {"slug": lifecycle_runbook}})
    if signal:
        plan.append(
            {
                "tool": "get_template_examples",
                "arguments": {"template_id": signal[0].template_id, "limit": 5},
            }
        )
    if component:
        plan.append({"tool": "component_timeline", "arguments": {"component": component}})
        plan.append({"tool": "node_breakdown", "arguments": {"component": component}})
    if signal:
        words = " ".join(_WORDS.findall(signal[0].template.lower())[:8])
        if len(words) >= 2:
            plan.append({"tool": "search_incidents", "arguments": {"query": words, "limit": 3}})
    runbook = next(
        (
            i.runbook_slug
            for i in inputs.similar
            if i.runbook_slug and i.applies_to(inputs.system, inputs.batch.features.components)
        ),
        None,
    )
    if runbook and runbook != lifecycle_runbook:
        plan.append({"tool": "get_runbook", "arguments": {"slug": runbook}})
    # A rival cause on another component gets its own timeline, so the two can be told apart.
    rival = next(
        (
            h.component
            for h in candidate_hypotheses(inputs)
            # Work that stops partway logs nothing, so a timeline cannot test it.
            if h.component and h.component != component and h.failure_mode != LIFECYCLE_CAUSE
        ),
        None,
    )
    if rival:
        plan.append({"tool": "component_timeline", "arguments": {"component": rival}})
    return plan


def _signal_in(buckets: Sequence[dict[str, Any]]) -> int:
    """Errors and warnings: many incidents in these systems only log at WARN."""
    return sum(int(b.get("errors", 0)) + int(b.get("warnings", 0)) for b in buckets)


def supports(hypothesis: Hypothesis, observation: Observation) -> bool:
    """Does an observation bear out the hypothesis? Transparent heuristics for the offline path."""
    data = observation.data or {}
    if not observation.ok:
        return False
    component = observation.arguments.get("component")
    if observation.tool == "component_timeline":
        return hypothesis.component == component and _signal_in(data.get("buckets", [])) > 0
    if observation.tool == "node_breakdown":
        erring = sum(1 for n in data.get("nodes", []) if n.get("errors") or n.get("warnings"))
        return component in (None, hypothesis.component) and erring >= 2
    if observation.tool == "search_incidents":
        top = data.get("incidents", [])[:2]
        return any(i.get("failure_mode") == hypothesis.failure_mode for i in top)
    if hypothesis.failure_mode == LIFECYCLE_CAUSE:
        # The unit's own lines, fetched by its ID, show the steps it took and the ones it did not.
        return (
            observation.tool == "search_logs"
            and _is_unit_key(str(observation.arguments.get("query", "")))
            and bool(data.get("lines"))
        ) or (
            observation.tool == "get_runbook"
            and hypothesis.failure_mode in data.get("failure_modes", [])
        )
    if observation.tool == "search_logs" and _is_unit_key(
        str(observation.arguments.get("query", ""))
    ):
        return False  # one unit's own lines speak to its lifecycle, not to other causes
    if observation.tool in ("get_template_examples", "search_logs"):
        lines = data.get("lines", [])
        return bool(lines) and (
            hypothesis.component is None
            or any(line.get("component") == hypothesis.component for line in lines)
        )
    if observation.tool == "get_runbook":
        return hypothesis.failure_mode in data.get("failure_modes", [])
    return False


def refutes(hypothesis: Hypothesis, observation: Observation) -> bool:
    """A clean timeline (no errors or warnings) for the suspected component counts against it,
    except for work that stops partway, which by its nature logs nothing."""
    data = observation.data or {}
    return (
        hypothesis.failure_mode != LIFECYCLE_CAUSE
        and observation.ok
        and observation.tool == "component_timeline"
        and hypothesis.component is not None
        and hypothesis.component == observation.arguments.get("component")
        and bool(data.get("buckets"))
        and _signal_in(data.get("buckets", [])) == 0
    )


class Investigator:
    """Rounds of plan-then-act: each round updates beliefs and runs tool calls in parallel.

    ``max_steps`` caps tool calls, ``max_rounds`` caps decision rounds (LLM calls), and
    ``max_parallel`` caps the calls one round may run at once.
    """

    def __init__(
        self,
        router: LLMRouter | None,
        *,
        max_steps: int = 6,
        max_hypotheses: int = 4,
        max_rounds: int = 2,
        max_parallel: int = 5,
        mode: Mode = "auto",
    ) -> None:
        self.router = router
        self.max_steps = max_steps
        self.max_hypotheses = max_hypotheses
        self.max_rounds = max_rounds
        self.max_parallel = max_parallel
        self.mode = mode

    def uses_llm(self) -> bool:
        if self.router is None or self.mode == "deterministic":
            return False
        return self.mode == "llm" or self.router.has_real_llm("investigator")

    # --- decisions -----------------------------------------------------------------------------

    def _deterministic(self, loop: _Loop, room: int) -> InvestigatorStep:
        new = [] if loop.hypotheses else candidate_hypotheses(loop.inputs)
        upcoming = [p for p in loop.plan if not _ran(loop, p["tool"], p["arguments"])][:room]
        if not upcoming:
            return InvestigatorStep(
                rationale="Planned checks complete.", new_hypotheses=new, finish=True
            )
        return InvestigatorStep(
            rationale=f"Run {', '.join(p['tool'] for p in upcoming)} to test the hypotheses.",
            new_hypotheses=new,
            calls=[
                ToolRequest(tool=p["tool"], arguments=ToolArguments(**p["arguments"]))
                for p in upcoming
            ],
        )

    async def _llm(self, loop: _Loop, round_no: int, room: int) -> InvestigatorStep | None:
        if self.router is None:
            return None
        allowed = [spec.name for spec in loop.belt.specs()]
        cited = self._context_evidence(loop)
        known = {e.id for e in cited}  # the model may cite only what it was shown
        ids = {h.id for h in loop.hypotheses}

        def check(output: InvestigatorStep) -> list[str]:
            errors = []
            bad = [c.tool for c in output.calls if c.tool not in allowed]
            if bad:
                errors.append(f"tools must be among {', '.join(allowed)}; got {', '.join(bad)}")
            if len(output.calls) > room:
                errors.append(f"at most {room} calls this round")
            for update in output.updates:
                if update.id not in ids:
                    errors.append(f"update for unknown hypothesis {update.id}")
                cited = [*update.supporting, *update.refuting]
                errors += [f"unknown evidence {e}" for e in cited if e not in known]
            return errors

        hypotheses = [
            h.model_dump(
                include={"id", "statement", "failure_mode", "component", "status", "confidence"}
            )
            for h in loop.hypotheses
        ]
        facts = {
            "system": loop.inputs.system,
            "round": round_no,
            "max_rounds": self.max_rounds,
            "max_parallel_calls": room,
            "tool_calls_left": room,
            "severity": str(loop.inputs.severity.severity),
            "allowed_actions": allowed,
            "tools": [spec.brief() for spec in loop.belt.specs()],
            "candidate_hypotheses": []
            if loop.hypotheses
            else [c.model_dump() for c in candidate_hypotheses(loop.inputs)],
            "suggested_plan": loop.plan,
        }
        schema = restrict_enum(strict_schema(InvestigatorStep), ["calls", "items", "tool"], allowed)
        try:
            result = await self.router.structured(
                "investigator",
                "investigator_step",
                build_messages(
                    "investigator_step",
                    facts,
                    cited,
                    # Hypotheses an LLM wrote and tool observations both quote logs: fenced.
                    untrusted_data={
                        "hypotheses": hypotheses,
                        "observations": [o.brief() for o in loop.observations[-6:]],
                    },
                    detail_chars=260,
                    data_chars=180,
                ),
                InvestigatorStep,
                json_schema=schema,
                validator=check,
                budget=loop.budget,
                temperature=0.0,
                max_tokens=1_600,  # reasoning models spend part of this before the JSON
            )
        except (BudgetExceededError, LLMError):
            return None
        return result.value

    @staticmethod
    def _context_evidence(loop: _Loop) -> list[Evidence]:
        """A compact evidence window: the window's key signals plus this loop's observations.

        Each step is one LLM call, so the context stays small: a few features, the top
        templates, similar incidents, and the latest tool results.
        """
        everything = loop.evidence.all()
        observed = {eid for o in loop.observations for eid in o.evidence_ids}

        def first(kind: EvidenceKind, n: int) -> list[Evidence]:
            return [e for e in everything if e.kind is kind][:n]

        tools = [e for e in everything if e.id in observed][-6:]
        return [
            *first(EvidenceKind.FEATURE, 3),
            *first(EvidenceKind.TEMPLATE, 5),
            *first(EvidenceKind.INCIDENT, 3),
            *tools,
        ]

    # --- belief updates ------------------------------------------------------------------------

    def _add(self, loop: _Loop, new: Sequence[NewHypothesis]) -> None:
        for item in new:
            duplicate = any(
                h.failure_mode == item.failure_mode and h.component == item.component
                for h in loop.hypotheses
            )
            if duplicate or len(loop.hypotheses) >= self.max_hypotheses:
                continue
            loop.hypotheses.append(
                Hypothesis(
                    id=f"H{len(loop.hypotheses) + 1}",
                    statement=item.statement,
                    failure_mode=item.failure_mode,
                    component=item.component,
                    confidence=0.4,
                )
            )

    @staticmethod
    def _apply(loop: _Loop, updates: Sequence[HypothesisUpdate]) -> None:
        index = {h.id: i for i, h in enumerate(loop.hypotheses)}
        for update in updates:
            if update.id not in index:
                continue
            i = index[update.id]
            current = loop.hypotheses[i]
            loop.hypotheses[i] = current.model_copy(
                update={
                    "status": update.status,
                    "confidence": update.confidence,
                    "supporting": list(dict.fromkeys([*current.supporting, *update.supporting])),
                    "refuting": list(dict.fromkeys([*current.refuting, *update.refuting])),
                }
            )
            loop.touched.add(update.id)

    @staticmethod
    def _score(loop: _Loop) -> None:
        """Final beliefs from the evidence, so "supported" never rests on a model's say-so.

        Each supporting observation adds confidence and a clean timeline refutes. When the LLM
        also judged a hypothesis, its confidence is averaged in and its refutation stands.
        """
        for i, hyp in enumerate(loop.hypotheses):
            support = [o for o in loop.observations if supports(hyp, o)]
            refute = [o for o in loop.observations if refutes(hyp, o)]
            confidence = 0.1 if refute else min(0.95, 0.4 + 0.15 * len(support))
            judged = hyp.id in loop.touched
            if judged:
                confidence = (confidence + hyp.confidence) / 2
            if refute or (judged and hyp.status == "refuted" and hyp.refuting):
                status = "refuted"
                confidence = min(confidence, 0.2)
            elif confidence >= 0.6:  # two independent supporting checks, or model + evidence
                status = "supported"
            else:
                status = "inconclusive" if loop.observations else "open"
            supporting = [e for o in support for e in o.evidence_ids]
            refuting = [e for o in refute for e in o.evidence_ids]
            loop.hypotheses[i] = hyp.model_copy(
                update={
                    "status": status,
                    "confidence": round(confidence, 2),
                    "supporting": list(dict.fromkeys([*hyp.supporting, *supporting]))[:8],
                    "refuting": list(dict.fromkeys([*hyp.refuting, *refuting]))[:8],
                }
            )

    def _room(self, calls: int, budget: BudgetGuard | None) -> int:
        """How many calls the next round may run: by parallelism, steps and the tool budget."""
        room = min(self.max_parallel, self.max_steps - calls)
        if budget is not None:
            room = min(room, budget.limits.max_tool_calls - budget.usage.tool_calls)
        return max(0, room)

    def _limit(self, calls: int, budget: BudgetGuard | None) -> str:
        """Why no more calls fit: the run's tool budget, or this investigation's step cap."""
        if budget is not None and budget.usage.tool_calls >= budget.limits.max_tool_calls:
            return "budget"
        return "max_steps" if calls >= self.max_steps else "finished"

    @staticmethod
    def _dedupe(loop: _Loop, requests: Sequence[ToolRequest]) -> list[ToolRequest]:
        seen: set[tuple[str, str]] = set()
        out = []
        for request in requests:
            args = loop.belt.prepared(request.tool, request.arguments.model_dump())
            key = (request.tool, json.dumps(args, sort_keys=True))
            if key in seen or _ran(loop, request.tool, args):
                continue
            seen.add(key)
            out.append(request)
        return out

    async def _call(
        self, loop: _Loop, request: ToolRequest, rationale: str, emit: Emit | None
    ) -> str:
        """Run one tool call and record its observation: "called", "refused" or "budget"."""
        args = {k: v for k, v in request.arguments.model_dump().items() if v is not None}
        ref = uuid.uuid4().hex[:12]  # links this call's start and result events
        if emit is not None:
            emit(
                "tool_call",
                {
                    "phase": "start",
                    "ref": ref,
                    "tool": request.tool,
                    "arguments": args,
                    "rationale": rationale,
                },
            )
        try:
            outcome = await loop.belt.call(request.tool, args)
        except ToolNotAllowedError as exc:
            observation = Observation(request.tool, args, False, str(exc), [])
            result = "refused"
        except BudgetExceededError:
            return "budget"
        else:
            observation = Observation(
                request.tool,
                dict(outcome.record.arguments),
                outcome.ok,
                outcome.record.summary,
                [outcome.evidence_id] if outcome.evidence_id else [],
                outcome.data,
            )
            result = "called"
        loop.observations.append(observation)
        if emit is not None:
            emit("tool_call", {"phase": "result", "ref": ref, **observation.brief()})
        return result

    # --- loop ----------------------------------------------------------------------------------

    async def run(
        self,
        inputs: InvestigationInputs,
        belt: ToolBelt,
        evidence: EvidenceStore,
        *,
        budget: BudgetGuard | None = None,
        emit: Emit | None = None,
    ) -> Investigation:
        tools = {spec.name for spec in belt.specs()}
        loop = _Loop(
            inputs,
            belt,
            evidence,
            budget,
            plan=[p for p in suggested_plan(inputs) if p["tool"] in tools],
        )
        # Start from the hypotheses the evidence suggests; the LLM may add its own.
        self._add(loop, candidate_hypotheses(inputs))
        llm = self.uses_llm()
        stopped = "max_rounds"
        calls = 0
        for round_no in range(self.max_rounds + 1):
            try:
                if budget is not None:
                    budget.check_step()
            except BudgetExceededError:
                stopped = "budget"
                break
            room = self._room(calls, budget)
            if round_no == self.max_rounds:
                break  # the last round's results are in; scoring decides from here
            decision = await self._llm(loop, round_no, room) if llm and room else None
            if decision is None:
                decision = self._deterministic(loop, room)
            self._add(loop, decision.new_hypotheses)
            self._apply(loop, decision.updates)
            if budget is not None:
                budget.record_step()
            requests = self._dedupe(loop, decision.calls)[:room]
            if decision.finish or not requests:
                stopped = "finished" if room else self._limit(calls, budget)
                break
            outcomes = await asyncio.gather(
                *(self._call(loop, request, decision.rationale, emit) for request in requests)
            )
            calls += sum(1 for outcome in outcomes if outcome == "called")
            if "budget" in outcomes:
                stopped = "budget"
                break
        self._score(loop)
        return self._conclude(loop, steps=calls, stopped=stopped)

    @staticmethod
    def _conclude(loop: _Loop, *, steps: int, stopped: str) -> Investigation:
        claims: list[Claim] = []
        for hyp in loop.hypotheses:
            eid = loop.evidence.add(
                EvidenceKind.HYPOTHESIS,
                f"{hyp.id} {hyp.status}: {hyp.statement}",
                source="investigator",
                detail=f"failure mode {hyp.failure_mode}; component {hyp.component or 'n/a'}",
                data={
                    "id": hyp.id,
                    "status": hyp.status,
                    "confidence": hyp.confidence,
                    "failure_mode": hyp.failure_mode,
                    "component": hyp.component,
                    "supporting": hyp.supporting,
                    "refuting": hyp.refuting,
                },
            )
            if hyp.status == "supported":
                claims.append(
                    Claim(
                        text=f"Supported: {hyp.statement}",
                        evidence_ids=[eid, *hyp.supporting[:3]],
                    )
                )
        supported = [h for h in loop.hypotheses if h.status == "supported"]
        # A supported named failure mode explains more than "the component is failing", which
        # is true of any cause on that component; the generic one leads only on its own.
        leading = (
            max(supported, key=lambda h: (h.failure_mode != GENERIC_CAUSE, h.confidence)).id
            if supported
            else None
        )
        return Investigation(
            hypotheses=loop.hypotheses,
            steps=steps,
            tool_calls=list(loop.belt.records),
            leading_hypothesis=leading,
            summary=claims,
            stopped_reason=stopped,
        )
