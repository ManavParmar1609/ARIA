"""State reducers, the run repository, the router's provider preference and review edits."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aria.config import get_app_config
from aria.contracts.base import Claim, EvidenceKind, Severity
from aria.contracts.report import IncidentReport, ReviewDecision
from aria.contracts.run import BudgetUsage, RunStatus
from aria.contracts.severity import SeverityAssessment
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db
from aria.evidence import EvidenceStore
from aria.graph.state import add_usage, merge_evidence, usage_delta
from aria.graph.store import SqlStore
from aria.llm.router import LLMRouter
from aria.reporting.review import apply_review


def _ev(i: int, title: str = "t") -> dict[str, object]:
    return {"id": f"E{i}", "kind": "feature", "title": title, "source": "test"}


@given(st.lists(st.integers(min_value=1, max_value=60), max_size=30), st.integers(1, 60))
def test_merge_evidence_is_a_union_ordered_by_id(ids: list[int], extra: int) -> None:
    current = [_ev(i) for i in dict.fromkeys(ids)]
    merged = merge_evidence(current, [_ev(extra, "new")])
    numbers = [int(str(item["id"])[1:]) for item in merged]
    assert numbers == sorted(set(ids) | {extra})
    assert next(item for item in merged if item["id"] == f"E{extra}")["title"] == "new"


def test_budget_usage_from_parallel_branches_adds_up() -> None:
    start = BudgetUsage(started_at=datetime(2026, 1, 1, tzinfo=UTC))
    total = add_usage(None, start.model_dump(mode="json"))
    branch_a = start.model_copy(update={"tokens_in": 100, "llm_calls": 1, "cost_usd": 0.01})
    branch_b = start.model_copy(update={"tool_calls": 3, "exhausted": ["tool_calls"]})
    total = add_usage(total, usage_delta(start, branch_a))
    total = add_usage(total, usage_delta(start, branch_b))
    usage = BudgetUsage.model_validate(total)
    assert (usage.tokens_in, usage.llm_calls, usage.tool_calls) == (100, 1, 3)
    assert usage.cost_usd == pytest.approx(0.01)
    assert usage.exhausted == ["tool_calls"]
    assert usage.started_at == start.started_at
    assert add_usage(total, None) == total


def test_run_repository_round_trip() -> None:
    engine = get_engine()
    init_db(engine)
    repo.create_run(engine, "r1", request={"system": "bgl"}, title="t", system="bgl")
    repo.create_run(engine, "r1", request={"ignored": True})  # idempotent
    repo.update_run(engine, "r1", status=RunStatus.RUNNING, severity="SEV2")
    run = repo.get_run(engine, "r1")
    assert run is not None
    assert (run["status"], run["severity"], run["request"]) == (
        "running",
        "SEV2",
        {"system": "bgl"},
    )
    with pytest.raises(ValueError, match="unknown run fields"):
        repo.update_run(engine, "r1", nonsense=1)
    with pytest.raises(KeyError):
        repo.update_run(engine, "missing", status=RunStatus.FAILED)
    first = repo.append_event(engine, "r1", "run_started")
    second = repo.append_event(engine, "r1", "node_started", node="plan", payload={"a": 1})
    assert (first.seq, second.seq) == (0, 1)
    assert [e.seq for e in repo.list_events(engine, "r1", after=0)] == [1]
    assert [r["id"] for r in repo.list_runs(engine, status="running")] == ["r1"]
    assert repo.list_runs(engine, status="published") == []


def test_store_prefix_search_treats_like_wildcards_literally() -> None:
    engine = get_engine()
    init_db(engine)
    store = SqlStore(engine)
    store.put(("feedback", "a_b"), "k1", {"v": 1})
    store.put(("feedback", "axb"), "k2", {"v": 2})
    store.put(("feedback", "a%"), "k3", {"v": 3})
    assert [i.key for i in store.search(("feedback", "a_b"))] == ["k1"]
    assert [i.key for i in store.search(("feedback", "a%"))] == ["k3"]
    assert len(store.search(("feedback",))) == 3


def test_router_preference_puts_a_provider_first_but_never_adds_fake() -> None:
    router = LLMRouter(get_app_config().llm)
    preferred = router.prefer("azure")
    assert preferred.config.routing["reporter"][0] == "azure"
    assert preferred.config.routing["adjudicator"][0] == "azure"
    faked = router.prefer("fake")
    assert faked.config.routing["reporter"][0] == "fake"
    assert "fake" not in faked.config.routing["adjudicator"]
    assert router.prefer(None) is router
    assert router.prefer("no-such-provider") is router
    # The original router keeps the configured chain.
    assert router.config.routing["reporter"] == get_app_config().llm.routing["reporter"]


def _report_and_assessment(store: EvidenceStore) -> tuple[IncidentReport, SeverityAssessment]:
    eid = store.add(EvidenceKind.FEATURE, "40 errors", source="parser")
    report = IncidentReport(
        report_id="rpt-1",
        run_id="r1",
        title="SEV2 · Errors",
        severity=Severity.SEV2,
        summary=[Claim(text="40 errors in the window.", evidence_ids=[eid])],
        evidence=store.all(),
    )
    assessment = SeverityAssessment(
        severity=Severity.SEV2,
        decided_by="rules",
        rule_severity=Severity.SEV2,
        rule_scores={Severity.SEV2: 2.0},
        probabilities={Severity.SEV2: 1.0},
        prediction_set=[Severity.SEV2],
        alpha=0.1,
        floor=Severity.SEV2,
        confidence=0.9,
        auditable=True,
    )
    return report, assessment


def test_approval_keeps_the_report_and_records_the_review() -> None:
    store = EvidenceStore()
    report, assessment = _report_and_assessment(store)
    decision = ReviewDecision(decision="approve", reviewer="ana", comment="ok")
    out, sev = apply_review(report, assessment, decision, store)
    assert out.version == 1
    assert out.summary == report.summary
    assert sev is assessment
    assert out.evidence[-1].kind is EvidenceKind.REVIEW
    assert "comment: ok" in out.evidence[-1].detail


def test_reviewer_may_go_below_the_floor_as_an_accountable_human_decision() -> None:
    store = EvidenceStore()
    report, assessment = _report_and_assessment(store)
    decision = ReviewDecision.model_validate(
        {"decision": "edit", "reviewer": "raj", "edits": {"severity": "SEV4", "note": "test env"}}
    )
    out, sev = apply_review(report, assessment, decision, store)
    assert (out.severity, sev.severity, sev.decided_by, sev.floor) == (
        Severity.SEV4,
        Severity.SEV4,
        "human",
        None,
    )
    assert out.summary[0].text == "Reviewer raj assigned SEV4; ARIA's assessment was SEV2."
    assert out.summary[1:] == report.summary
    assert out.open_questions == ["Reviewer note: test env"]


def test_a_summary_line_the_reviewer_kept_still_cites_its_evidence() -> None:
    store = EvidenceStore()
    report, assessment = _report_and_assessment(store)
    decision = ReviewDecision.model_validate(
        {
            "decision": "edit",
            "reviewer": "ana",
            "edits": {"summary": ["40 errors in the window.", "Only two DataNodes failed."]},
        }
    )
    out, _ = apply_review(report, assessment, decision, store)
    assert out.summary[0] == report.summary[0]  # kept: still cites the parser's evidence
    assert out.summary[1].evidence_ids == [out.evidence[-1].id]  # new: cites the review
