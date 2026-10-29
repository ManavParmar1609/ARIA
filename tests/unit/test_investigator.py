"""The investigator's ReAct loop: deterministic plan, LLM steps, refusals, budgets and evidence."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from aria.agents.investigator import (
    INVESTIGATOR_TOOLS,
    InvestigationInputs,
    Investigator,
    suggested_plan,
)
from aria.config import BudgetConfig, GuardrailConfig
from aria.contracts.base import EvidenceKind
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db.engine import get_engine, init_db
from aria.evidence import EvidenceStore
from aria.llm.base import LLMError, LLMResult, Usage
from aria.llm.budget import BudgetGuard
from aria.llm.schemas import InvestigatorStep
from aria.mcp.client import ToolBelt
from aria.mcp.server import build_server
from aria.parsing.parser import QUARANTINE_FLAG, parse_lines
from aria.retrieval.memory import IncidentMemory
from aria.retrieval.retriever import build_query
from aria.retrieval.runbooks import load_runbooks
from aria.retrieval.runlog import store_run_lines
from aria.retrieval.seed import incident_from_scenario
from aria.services import Services

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
        run_id=RUN,
        evidence=evidence,
        **kwargs,
    )


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
    assert [c.tool for c in result.tool_calls] == [p["tool"] for p in plan]
    assert all(c.arguments.get("run_id", RUN) == RUN for c in result.tool_calls)
    assert result.stopped_reason == "finished"
    assert result.leading_hypothesis is not None
    assert len(events) == len(plan)
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
        {"rationale": "wipe it", "action": "delete_run"},
        {
            "rationale": "cite junk",
            "action": "node_breakdown",
            "updates": [
                {"id": "H9", "status": "supported", "confidence": 0.9, "supporting": ["E999"]}
            ],
        },
    ]
    async with _belt(services, evidence) as belt:
        result = await Investigator(_Scripted(bad), mode="llm").run(inputs, belt, evidence)  # type: ignore[arg-type]
    assert "delete_run" not in {c.tool for c in result.tool_calls}
    assert all(h.id != "H9" for h in result.hypotheses)
    assert result.tool_calls[0].tool == suggested_plan(inputs)[0]["tool"]


async def test_belt_refusals_are_recorded_and_the_tool_budget_stops_the_loop(
    setup: tuple[Services, InvestigationInputs, EvidenceStore],
) -> None:
    services, inputs, evidence = setup
    steps = [
        {
            "rationale": "timeline",
            "action": "component_timeline",
            "arguments": {"component": "KERNEL"},
        },
        {"rationale": "runbook", "action": "get_runbook", "arguments": {"slug": "generic-triage"}},
        {"rationale": "again", "action": "get_runbook", "arguments": {"slug": "generic-triage"}},
    ]
    budget = BudgetGuard(BudgetConfig(max_tool_calls=1))
    allowed = {"component_timeline", "get_runbook"}
    async with _belt(services, evidence, allowed=allowed, budget=budget) as belt:
        belt.allowed = frozenset({"get_runbook"})  # the allowlist shrinks after tools were listed
        investigator = Investigator(_Scripted(steps), mode="llm")  # type: ignore[arg-type]
        result = await investigator.run(inputs, belt, evidence, budget=budget)
    first = result.tool_calls[0]
    assert (first.tool, first.ok) == ("component_timeline", False)
    assert first.summary.startswith("refused")
    assert [c.tool for c in result.tool_calls[1:]] == ["get_runbook"]
    assert result.stopped_reason == "budget"
    assert budget.usage.tool_calls == 1


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
