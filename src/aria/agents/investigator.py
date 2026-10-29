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

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from aria.contracts.base import Claim, EvidenceKind
from aria.contracts.parsing import ParsedBatch
from aria.contracts.retrieval import Hypothesis, Investigation, SimilarIncident
from aria.contracts.severity import SeverityAssessment
from aria.evidence import EvidenceStore
from aria.llm.base import BudgetExceededError, LLMError
from aria.llm.budget import BudgetGuard
from aria.llm.jsonschema import restrict_enum, strict_schema
from aria.llm.prompts import build_messages
from aria.llm.router import LLMRouter
from aria.llm.schemas import HypothesisUpdate, InvestigatorStep, NewHypothesis, ToolArguments
from aria.mcp.client import ToolBelt, ToolNotAllowedError
from aria.parsing.parser import QUARANTINE_FLAG

INVESTIGATOR_TOOLS = (
    "search_logs",
    "get_template_examples",
    "component_timeline",
    "node_breakdown",
    "search_incidents",
    "get_runbook",
)
_WORDS = re.compile(r"[a-z][a-z0-9_]{2,}")
Emit = Callable[[str, dict[str, Any]], None]
Mode = Literal["auto", "llm", "deterministic"]


@dataclass
class InvestigationInputs:
    run_id: str
    system: str
    batch: ParsedBatch
    severity: SeverityAssessment
    similar: list[SimilarIncident] = field(default_factory=list)


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
    features = batch.features
    if features.critical_components:
        return features.critical_components[0]
    counts: dict[str, int] = {}
    for event in batch.events:
        # Quarantined lines are shown to reviewers but must never steer the investigation.
        quarantined = QUARANTINE_FLAG in event.flags
        if event.level in ("ERROR", "FATAL") and event.component and not quarantined:
            counts[event.component] = counts.get(event.component, 0) + 1
    if counts:
        return max(counts, key=counts.__getitem__)
    return features.components[0] if features.components else None


def candidate_hypotheses(inputs: InvestigationInputs, *, limit: int = 3) -> list[NewHypothesis]:
    """Plausible causes to test, from similar incidents and the window's own error signals."""
    component = _top_component(inputs.batch)
    seen: set[str] = set()
    out: list[NewHypothesis] = []
    for incident in inputs.similar:
        if incident.failure_mode in seen or incident.failure_mode == "none":
            continue
        seen.add(incident.failure_mode)
        label = incident.failure_mode.replace("_", " ")
        out.append(
            NewHypothesis(
                statement=f"{label.capitalize()}, as in past incident {incident.incident_id}",
                failure_mode=incident.failure_mode,
                component=component,
            )
        )
    errors = [t for t in inputs.batch.templates if t.error_like]
    if errors and component and "component_errors" not in seen:
        top = errors[0]
        out.append(
            NewHypothesis(
                statement=f'{component} is failing: "{top.template[:80]}" repeats {top.count} times',
                failure_mode="component_errors",
                component=component,
            )
        )
    return out[:limit]


def suggested_plan(inputs: InvestigationInputs) -> list[dict[str, Any]]:
    """A sensible default sequence of tool calls; the LLM may deviate within the allowlist."""
    plan: list[dict[str, Any]] = []
    errors = [t for t in inputs.batch.templates if t.error_like]
    component = _top_component(inputs.batch)
    if errors:
        plan.append(
            {
                "tool": "get_template_examples",
                "arguments": {"template_id": errors[0].template_id, "limit": 5},
            }
        )
    if component:
        plan.append({"tool": "component_timeline", "arguments": {"component": component}})
        plan.append({"tool": "node_breakdown", "arguments": {"component": component}})
    if errors:
        words = " ".join(_WORDS.findall(errors[0].template.lower())[:8])
        if len(words) >= 2:
            plan.append({"tool": "search_incidents", "arguments": {"query": words, "limit": 3}})
    runbook = next((i.runbook_slug for i in inputs.similar if i.runbook_slug), None)
    if runbook:
        plan.append({"tool": "get_runbook", "arguments": {"slug": runbook}})
    return plan


def _errors_in(buckets: Sequence[dict[str, Any]]) -> int:
    return sum(int(b.get("errors", 0)) for b in buckets)


def supports(hypothesis: Hypothesis, observation: Observation) -> bool:
    """Does an observation bear out the hypothesis? Transparent heuristics for the offline path."""
    data = observation.data or {}
    if not observation.ok:
        return False
    component = observation.arguments.get("component")
    if observation.tool == "component_timeline":
        return hypothesis.component == component and _errors_in(data.get("buckets", [])) > 0
    if observation.tool == "node_breakdown":
        erring = sum(1 for n in data.get("nodes", []) if n.get("errors"))
        return component in (None, hypothesis.component) and erring >= 2
    if observation.tool == "search_incidents":
        top = data.get("incidents", [])[:2]
        return any(i.get("failure_mode") == hypothesis.failure_mode for i in top)
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
    """A clean timeline for the suspected component counts against the hypothesis."""
    data = observation.data or {}
    return (
        observation.ok
        and observation.tool == "component_timeline"
        and hypothesis.component is not None
        and hypothesis.component == observation.arguments.get("component")
        and bool(data.get("buckets"))
        and _errors_in(data.get("buckets", [])) == 0
    )


class Investigator:
    def __init__(
        self,
        router: LLMRouter | None,
        *,
        max_steps: int = 6,
        max_hypotheses: int = 4,
        mode: Mode = "auto",
    ) -> None:
        self.router = router
        self.max_steps = max_steps
        self.max_hypotheses = max_hypotheses
        self.mode = mode

    def uses_llm(self) -> bool:
        if self.router is None or self.mode == "deterministic":
            return False
        return self.mode == "llm" or self.router.has_real_llm("investigator")

    # --- decisions -----------------------------------------------------------------------------

    def _deterministic(self, loop: _Loop, step: int) -> InvestigatorStep:
        done = {o.tool for o in loop.observations}
        new = [] if loop.hypotheses else candidate_hypotheses(loop.inputs)
        upcoming = None
        if step < self.max_steps:
            upcoming = next((p for p in loop.plan if p["tool"] not in done), None)
        if upcoming is None:
            return InvestigatorStep(
                rationale="Planned checks complete.", new_hypotheses=new, action="finish"
            )
        return InvestigatorStep(
            rationale=f"Run {upcoming['tool']} to test the hypotheses.",
            new_hypotheses=new,
            action=upcoming["tool"],
            arguments=ToolArguments(**upcoming["arguments"]),
        )

    async def _llm(self, loop: _Loop, step: int) -> InvestigatorStep | None:
        if self.router is None:
            return None
        allowed = [spec.name for spec in loop.belt.specs()]
        actions = [*allowed, "finish"]
        known = {e.id for e in loop.evidence.all()}
        ids = {h.id for h in loop.hypotheses}

        def check(output: InvestigatorStep) -> list[str]:
            errors = []
            if output.action not in actions:
                errors.append(f"action must be one of {', '.join(actions)}")
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
            "step": step,
            "max_steps": self.max_steps,
            "severity": str(loop.inputs.severity.severity),
            "allowed_actions": actions,
            "tools": [spec.brief() for spec in loop.belt.specs()],
            "hypotheses": hypotheses,
            "observations": [o.brief() for o in loop.observations[-6:]],
            "candidate_hypotheses": []
            if loop.hypotheses
            else [c.model_dump() for c in candidate_hypotheses(loop.inputs)],
            "suggested_plan": loop.plan,
        }
        kinds = {EvidenceKind.TEMPLATE, EvidenceKind.FEATURE, EvidenceKind.TOOL}
        cited = [e for e in loop.evidence.all() if e.kind in kinds]
        schema = restrict_enum(strict_schema(InvestigatorStep), ["action"], actions)
        try:
            result = await self.router.structured(
                "investigator",
                "investigator_step",
                build_messages("investigator_step", facts, cited[-25:]),
                InvestigatorStep,
                json_schema=schema,
                validator=check,
                budget=loop.budget,
                temperature=0.0,
                max_tokens=900,
            )
        except (BudgetExceededError, LLMError):
            return None
        return result.value

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
        """Offline scoring for hypotheses the LLM did not judge: support adds confidence."""
        for i, hyp in enumerate(loop.hypotheses):
            if hyp.id in loop.touched:
                continue
            support = [o for o in loop.observations if supports(hyp, o)]
            refute = [o for o in loop.observations if refutes(hyp, o)]
            confidence = 0.1 if refute else min(0.95, 0.4 + 0.15 * len(support))
            if refute:
                status = "refuted"
            elif confidence >= 0.6:
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
        llm = self.uses_llm()
        stopped = "max_steps"
        calls = 0
        for step in range(self.max_steps + 1):
            try:
                if budget is not None:
                    budget.check_step()
            except BudgetExceededError:
                stopped = "budget"
                break
            decision = await self._llm(loop, step) if llm else None
            if decision is None:
                decision = self._deterministic(loop, step)
            self._add(loop, decision.new_hypotheses)
            self._apply(loop, decision.updates)
            if budget is not None:
                budget.record_step()
            if decision.action == "finish" or step >= self.max_steps:
                stopped = "finished" if decision.action == "finish" else "max_steps"
                break
            args = {k: v for k, v in decision.arguments.model_dump().items() if v is not None}
            if emit is not None:
                emit(
                    "tool_call",
                    {"tool": decision.action, "arguments": args, "rationale": decision.rationale},
                )
            try:
                outcome = await belt.call(decision.action, args)
            except ToolNotAllowedError as exc:
                loop.observations.append(Observation(decision.action, args, False, str(exc), []))
                continue
            except BudgetExceededError:
                stopped = "budget"
                break
            calls += 1
            loop.observations.append(
                Observation(
                    decision.action,
                    dict(outcome.record.arguments),
                    outcome.ok,
                    outcome.record.summary,
                    [outcome.evidence_id] if outcome.evidence_id else [],
                    outcome.data,
                )
            )
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
        leading = max(supported, key=lambda h: h.confidence).id if supported else None
        return Investigation(
            hypotheses=loop.hypotheses,
            steps=steps,
            tool_calls=list(loop.belt.records),
            leading_hypothesis=leading,
            summary=claims,
            stopped_reason=stopped,
        )
