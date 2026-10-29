"""The investigator's ReAct loop: deterministic plan, LLM steps, refusals, budgets and evidence."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from aria.agents.investigator import (
    GENERIC_CAUSE,
    INVESTIGATOR_TOOLS,
    LIFECYCLE_CAUSE,
    InvestigationInputs,
    Investigator,
    Observation,
    _Loop,
    candidate_hypotheses,
    refutes,
    suggested_plan,
    supports,
)
from aria.config import BudgetConfig, GuardrailConfig
from aria.contracts.base import EvidenceKind
from aria.contracts.retrieval import Hypothesis, RunbookRef
from aria.data.real import real_incident
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db.engine import get_engine, init_db
from aria.evidence import EvidenceStore
from aria.llm.base import LLMError, LLMResult, Usage
from aria.llm.budget import BudgetGuard
from aria.llm.schemas import InvestigatorStep
from aria.mcp.client import ToolBelt
from aria.mcp.server import build_server
from aria.parsing.parser import QUARANTINE_FLAG, parse_lines
from aria.parsing.signals import signal_templates
from aria.retrieval.memory import IncidentMemory
from aria.retrieval.retriever import build_query
from aria.retrieval.runbooks import load_runbooks
from aria.retrieval.runlog import store_run_lines
from aria.retrieval.seed import incident_from_scenario
from aria.services import Services
from aria.severity.training import known_templates

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
RUN = "run-inv-1"


@pytest.fixture
async def setup() -> AsyncIterator[tuple[Services, InvestigationInputs, EvidenceStore]]:
    engine = get_engine()
    init_db(engine)
    builder = ScenarioBuilder(LinePools.from_loghub(FIXTURES))
    runbooks = load_runbooks(Path("runbooks"))
    seeded = builder.build("bgl.kernel_panic", seed=7, nodes=3, duration_min=5)
    await IncidentMemory(engine, None).bulk_insert([incident_from_scenario(seeded, runbooks)])
    services = await Services.create()
    scenario = builder.build("bgl.kernel_panic", seed=8, nodes=4, duration_min=6)
    evidence = EvidenceStore()
    out = parse_lines(scenario.lines, system="bgl", guard=GuardrailConfig(), evidence=evidence)
    store_run_lines(engine, RUN, "bgl", out.lines)
    severity = await services.severity.assess(
        out.batch.features, system="bgl", evidence=evidence, use_llm=False
    )
    retrieval = await services.retriever.retrieve(
        build_query(out.batch), evidence=evidence, use_llm=False
    )
    inputs = InvestigationInputs(RUN, "bgl", out.batch, severity.assessment, retrieval.incidents)
    yield services, inputs, evidence
    await services.aclose()


def _belt(services: Services, evidence: EvidenceStore, **kwargs: Any) -> ToolBelt:
    return ToolBelt(
        build_server(services),
        allowed=kwargs.pop("allowed", INVESTIGATOR_TOOLS),
        agent="investigator",
        run_id=kwargs.pop("run_id", RUN),
        evidence=evidence,
        **kwargs,
    )


@dataclass
class Hdfs:
    services: Services
    builder: ScenarioBuilder
    known: tuple[str, ...]


@pytest.fixture
async def hdfs() -> AsyncIterator[Hdfs]:
    """Memory holds one past HDFS block-serve incident, a problem that only logs at WARN."""
    engine = get_engine()
    init_db(engine)
    builder = ScenarioBuilder(LinePools.from_loghub(FIXTURES))
    known = known_templates(builder, "hdfs")
    past = builder.build("hdfs.block_serve_exceptions", seed=7, nodes=3, duration_min=5)
    await IncidentMemory(engine, None).bulk_insert(
        [incident_from_scenario(past, load_runbooks(Path("runbooks")), known)]
    )
    services = await Services.create()
    yield Hdfs(services, builder, known)
    await services.aclose()


async def _inputs(
    case: Hdfs, lines: list[str], run_id: str
) -> tuple[InvestigationInputs, EvidenceStore]:
    evidence = EvidenceStore()
    out = parse_lines(
        lines, system="hdfs", guard=GuardrailConfig(), evidence=evidence, known_templates=case.known
    )
    store_run_lines(case.services.engine, run_id, "hdfs", out.lines)
    severity = await case.services.severity.assess(
        out.batch.features, system="hdfs", evidence=evidence, use_llm=False
    )
    retrieval = await case.services.retriever.retrieve(
        build_query(out.batch), evidence=evidence, use_llm=False
    )
    inputs = InvestigationInputs(
        run_id, "hdfs", out.batch, severity.assessment, retrieval.incidents
    )
    return inputs, evidence


async def test_deterministic_loop_follows_the_plan_and_cites_its_hypotheses(
    setup: tuple[Services, InvestigationInputs, EvidenceStore],
) -> None:
    services, inputs, evidence = setup
    plan = suggested_plan(inputs)
    events: list[tuple[str, dict[str, Any]]] = []
    async with _belt(services, evidence) as belt:
        result = await Investigator(None).run(
            inputs, belt, evidence, emit=lambda k, p: events.append((k, p))
        )
    assert sorted(c.tool for c in result.tool_calls) == sorted(p["tool"] for p in plan)
    calls = {(c.tool, json.dumps(c.arguments, sort_keys=True)) for c in result.tool_calls}
    assert len(calls) == len(result.tool_calls)  # no call runs twice
    assert all(c.arguments.get("run_id", RUN) == RUN for c in result.tool_calls)
    assert result.stopped_reason == "finished"
    assert result.leading_hypothesis is not None
    starts = [p for kind, p in events if kind == "tool_call" and p["phase"] == "start"]
    results = [p for kind, p in events if kind == "tool_call" and p["phase"] == "result"]
    assert sorted(p["tool"] for p in starts) == sorted(p["tool"] for p in plan)
    assert {p["ref"] for p in starts} == {p["ref"] for p in results}
    hypotheses = [e for e in evidence.all() if e.kind is EvidenceKind.HYPOTHESIS]
    assert {e.data["id"] for e in hypotheses} == {h.id for h in result.hypotheses}
    assert all("confidence" in e.data for e in hypotheses)
    for claim in result.summary:
        assert all(eid in evidence for eid in claim.evidence_ids)


async def test_llm_steps_drive_the_loop_through_the_router(
    setup: tuple[Services, InvestigationInputs, EvidenceStore],
) -> None:
    services, inputs, evidence = setup
    async with _belt(services, evidence) as belt:
        result = await Investigator(services.router, mode="llm").run(inputs, belt, evidence)
    assert result.tool_calls
    assert {c.tool for c in result.tool_calls} <= set(INVESTIGATOR_TOOLS)
    assert any(h.status == "supported" for h in result.hypotheses)


class _Scripted:
    """A router stand-in that answers with fixed steps, checked by the investigator's validator."""

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self.steps = steps

    def has_real_llm(self, role: str) -> bool:
        return True

    async def structured(self, *args: Any, validator: Any = None, **kwargs: Any) -> Any:
        if not self.steps:
            msg = "no more scripted steps"
            raise LLMError(msg)
        value = InvestigatorStep.model_validate(self.steps.pop(0))
        errors = validator(value) if validator else []
        if errors:
            raise LLMError("; ".join(errors))
        return LLMResult(value=value, text="", provider="scripted", model="m", usage=Usage())


async def test_off_list_actions_and_unknown_evidence_fall_back_to_the_plan(
    setup: tuple[Services, InvestigationInputs, EvidenceStore],
) -> None:
    services, inputs, evidence = setup
    bad = [
        {"rationale": "wipe it", "calls": [{"tool": "delete_run"}]},
        {
            "rationale": "cite junk",
            "calls": [{"tool": "node_breakdown"}],
            "updates": [
                {"id": "H9", "status": "supported", "confidence": 0.9, "supporting": ["E999"]}
            ],
        },
    ]
    async with _belt(services, evidence) as belt:
        investigator = Investigator(_Scripted(bad), mode="llm")  # type: ignore[arg-type]
        result = await investigator.run(inputs, belt, evidence)
    assert "delete_run" not in {c.tool for c in result.tool_calls}
    assert all(h.id != "H9" for h in result.hypotheses)
    assert sorted(c.tool for c in result.tool_calls) == sorted(
        p["tool"] for p in suggested_plan(inputs)
    )
    assert result.stopped_reason == "finished"


async def test_belt_refusals_are_recorded_and_the_tool_budget_stops_the_loop(
    setup: tuple[Services, InvestigationInputs, EvidenceStore],
) -> None:
    services, inputs, evidence = setup
    steps = [
        {
            "rationale": "timeline",
            "calls": [{"tool": "component_timeline", "arguments": {"component": "KERNEL"}}],
        },
        {
            "rationale": "runbook",
            "calls": [{"tool": "get_runbook", "arguments": {"slug": "generic-triage"}}],
        },
        {
            "rationale": "another",
            "calls": [{"tool": "get_runbook", "arguments": {"slug": "zookeeper-quorum-loss"}}],
        },
    ]
    budget = BudgetGuard(BudgetConfig(max_tool_calls=1))
    allowed = {"component_timeline", "get_runbook"}
    async with _belt(services, evidence, allowed=allowed, budget=budget) as belt:
        belt.allowed = frozenset({"get_runbook"})  # the allowlist shrinks after tools were listed
        investigator = Investigator(_Scripted(steps), mode="llm", max_rounds=3)  # type: ignore[arg-type]
        result = await investigator.run(inputs, belt, evidence, budget=budget)
    first = result.tool_calls[0]
    assert (first.tool, first.ok) == ("component_timeline", False)
    assert first.summary.startswith("refused")
    assert [c.tool for c in result.tool_calls[1:]] == ["get_runbook"]
    assert result.stopped_reason == "budget"
    assert budget.usage.tool_calls == 1


async def test_parallel_rounds_need_few_decisions(
    setup: tuple[Services, InvestigationInputs, EvidenceStore],
) -> None:
    services, inputs, evidence = setup
    async with _belt(services, evidence) as belt:
        result = await Investigator(services.router, mode="llm").run(inputs, belt, evidence)
    plan = suggested_plan(inputs)
    assert sorted(c.tool for c in result.tool_calls) == sorted(p["tool"] for p in plan)
    assert result.steps == len(plan)
    assert result.stopped_reason == "finished"


def test_quarantined_lines_never_choose_the_component(
    setup: tuple[Services, InvestigationInputs, EvidenceStore],
) -> None:
    _, inputs, _ = setup
    batch = inputs.batch
    event = batch.events[0].model_copy(
        update={"level": "FATAL", "component": "ATTACKER", "flags": [QUARANTINE_FLAG]}
    )
    poisoned = batch.model_copy(update={"events": [event] * 50 + list(batch.events)})
    plain = suggested_plan(inputs)
    tainted = suggested_plan(
        InvestigationInputs(RUN, "bgl", poisoned, inputs.severity, inputs.similar)
    )
    assert plain == tainted


async def test_warning_level_incidents_are_tested_on_the_component_that_warns(hdfs: Hdfs) -> None:
    scenario = hdfs.builder.build("hdfs.block_serve_exceptions", seed=8, nodes=4, duration_min=6)
    inputs, evidence = await _inputs(hdfs, scenario.lines, "run-inv-hdfs")
    assert inputs.batch.features.error_events == 0  # the incident only logs at WARN
    async with _belt(hdfs.services, evidence, run_id="run-inv-hdfs") as belt:
        result = await Investigator(None).run(inputs, belt, evidence)
    leading = next(h for h in result.hypotheses if h.id == result.leading_hypothesis)
    assert leading.failure_mode == "block_serve_exceptions"
    assert leading.status == "supported"
    assert leading.component == "dfs.DataNode$DataXceiver"
    timeline = next(c for c in result.tool_calls if c.tool == "component_timeline")
    assert "warnings" in timeline.summary


async def test_a_window_without_signal_supports_no_hypothesis(hdfs: Hdfs) -> None:
    quiet = hdfs.builder.build_quiet("hdfs", seed=5, duration_min=10)
    inputs, evidence = await _inputs(hdfs, quiet.lines, "run-inv-quiet")
    assert not signal_templates(inputs.batch)
    async with _belt(hdfs.services, evidence, run_id="run-inv-quiet") as belt:
        result = await Investigator(None).run(inputs, belt, evidence)
    assert result.leading_hypothesis is None
    assert all(h.status != "supported" for h in result.hypotheses)
    assert "node_breakdown" not in {c.tool for c in result.tool_calls}  # nowhere to look


def test_a_named_cause_leads_over_the_generic_one() -> None:
    def hypothesis(hid: str, mode: str, confidence: float) -> Hypothesis:
        return Hypothesis(
            id=hid,
            statement=f"{mode} on dfs.DataNode",
            failure_mode=mode,
            component="dfs.DataNode",
            status="supported",
            confidence=confidence,
        )

    loop = _Loop(
        inputs=cast("InvestigationInputs", None),
        belt=cast("ToolBelt", SimpleNamespace(records=[])),
        evidence=EvidenceStore(),
        budget=None,
        plan=[],
        hypotheses=[
            hypothesis("H1", GENERIC_CAUSE, 0.95),
            hypothesis("H2", "block_serve_exceptions", 0.7),
        ],
    )
    assert Investigator._conclude(loop, steps=0, stopped="finished").leading_hypothesis == "H2"
    loop.hypotheses = loop.hypotheses[:1]
    assert Investigator._conclude(loop, steps=0, stopped="finished").leading_hypothesis == "H1"


# --- units of work that stop partway ------------------------------------------------------------


def _real_hdfs_inputs(evidence: EvidenceStore) -> InvestigationInputs:
    """The committed cut of a real Hadoop cluster's log, where some blocks never finish."""
    lines = real_incident("hdfs-silent-block-failures").lines()  # type: ignore[union-attr]
    out = parse_lines(lines, system="hdfs", guard=GuardrailConfig(), evidence=evidence)
    assert out.batch.flows.broken >= 3
    runbook = RunbookRef(
        slug="hdfs-unfinished-writes", title="HDFS block writes", failure_modes=[LIFECYCLE_CAUSE]
    )
    severity = cast("Any", SimpleNamespace(severity="SEV3"))
    return InvestigationInputs("run-real", "hdfs", out.batch, severity, [], [runbook])


def test_work_that_stops_partway_is_the_first_cause_to_test() -> None:
    inputs = _real_hdfs_inputs(EvidenceStore())
    first = candidate_hypotheses(inputs)[0]
    assert first.failure_mode == LIFECYCLE_CAUSE
    assert first.statement.startswith("Work on HDFS blocks stops partway")
    plan = suggested_plan(inputs)
    keys = inputs.batch.flows.examples
    assert plan[0] == {"tool": "search_logs", "arguments": {"query": keys[0].key, "limit": 20}}
    assert {"tool": "get_runbook", "arguments": {"slug": "hdfs-unfinished-writes"}} in plan


def test_a_units_own_lines_support_it_and_a_quiet_timeline_does_not_refute_it() -> None:
    hypothesis = Hypothesis(
        id="H1",
        statement="Work on HDFS blocks stops partway",
        failure_mode=LIFECYCLE_CAUSE,
        confidence=0.4,
    )
    lines = Observation("search_logs", {"query": "blk_123"}, True, "", [], {"lines": [{"x": 1}]})
    other = Observation("search_logs", {"query": "exception"}, True, "", [], {"lines": [{"x": 1}]})
    quiet = Observation(
        "component_timeline",
        {"component": "dfs.DataNode"},
        True,
        "",
        [],
        {"buckets": [{"lines": 40, "errors": 0, "warnings": 0}]},
    )
    assert supports(hypothesis, lines)
    assert not supports(hypothesis, other)
    assert not refutes(hypothesis.model_copy(update={"component": "dfs.DataNode"}), quiet)
