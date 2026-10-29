"""Evaluation harness: metric definitions, the CI gate, sampling, attacks and the report."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aria.config import GuardrailConfig
from aria.contracts.parsing import WindowFeatures
from aria.contracts.run import EventKind, RunEvent
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.evals import edge as ed
from aria.evals import metrics as m
from aria.evals import parsing as ps
from aria.evals import pipeline as pl
from aria.evals import report
from aria.evals import run as ev
from aria.evals import severity as sv
from aria.evidence import EvidenceStore
from aria.parsing.parser import parse_lines

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
labels = st.sampled_from(m.CLASSES)
pairs = st.lists(st.tuples(labels, labels), min_size=1, max_size=40)


@pytest.fixture(scope="module")
def builder() -> ScenarioBuilder:
    return ScenarioBuilder(LinePools.from_loghub(FIXTURES))


# --- metrics -----------------------------------------------------------------------------------


@given(pairs)
def test_every_case_is_exact_under_or_over_triaged(cases: list[tuple[str, str]]) -> None:
    truth, pred = zip(*cases, strict=True)
    total = m.accuracy(truth, pred) + m.under_triage(truth, pred) + m.over_triage(truth, pred)
    assert total == pytest.approx(1.0)
    # Severe under-triage is a rate over SEV1/SEV2 incidents only; as counts, those cases are a
    # subset of all under-triaged ones.
    serious = sum(t in ("SEV1", "SEV2") for t in truth)
    severe = m.severe_under_triage(truth, pred) * serious
    assert severe <= m.under_triage(truth, pred) * len(truth) + 1e-9
    low, high = m.bootstrap(m.accuracy, list(truth), list(pred), rounds=50)
    assert low <= m.accuracy(truth, pred) + 1e-9
    assert high >= m.accuracy(truth, pred) - 1e-9
    assert sum(map(sum, m.confusion(truth, pred))) == len(truth)


@given(pairs)
def test_macro_f1_matches_sklearn(cases: list[tuple[str, str]]) -> None:
    from sklearn.metrics import f1_score

    truth, pred = zip(*cases, strict=True)
    present = sorted(set(truth) | set(pred))
    expected = f1_score(truth, pred, labels=present, average="macro", zero_division=0)
    assert m.macro_f1(truth, pred) == pytest.approx(expected)


def test_under_triage_only_counts_the_costly_direction() -> None:
    truth = ["SEV1", "SEV2", "SEV3", "SEV4"]
    pred = ["SEV3", "SEV2", "SEV2", "SEV4"]  # one serious incident downgraded, one upgraded
    assert m.under_triage(truth, pred) == 0.25
    assert m.over_triage(truth, pred) == 0.25
    assert m.severe_under_triage(truth, pred) == 0.5  # of the two SEV1/SEV2 incidents
    assert m.confusion(truth, pred)[0] == [0, 0, 1, 0]  # rows are the truth


def test_quadratic_kappa_penalises_far_misses_more() -> None:
    truth = ["SEV1", "SEV2", "SEV3", "SEV4"] * 3
    near = ["SEV2", "SEV2", "SEV3", "SEV4"] * 3
    far = ["SEV4", "SEV2", "SEV3", "SEV4"] * 3
    assert m.quadratic_kappa(truth, truth) == pytest.approx(1.0)
    assert m.quadratic_kappa(truth, near) > m.quadratic_kappa(truth, far)


def test_calibration_scores() -> None:
    truth = ["SEV1", "SEV2"]
    sure_and_right = [{"SEV1": 1.0}, {"SEV2": 1.0}]
    sure_and_wrong = [{"SEV2": 1.0}, {"SEV1": 1.0}]
    assert m.expected_calibration_error(sure_and_right, truth) == 0.0
    assert m.expected_calibration_error(sure_and_wrong, truth) == pytest.approx(1.0)
    assert m.brier(sure_and_right, truth) == 0.0
    assert m.brier(sure_and_wrong, truth) == pytest.approx(2.0)


def test_ndcg_rewards_hits_near_the_top() -> None:
    assert m.ndcg_at_k([["a", "a", "a"]], ["a"], 3) == pytest.approx(1.0)
    assert m.ndcg_at_k([["b", "a"]], ["a"], 3, relevant=1) == pytest.approx(1 / math.log2(3))
    assert m.ndcg_at_k([["a", "b"]], ["a"], 3, relevant=1) == pytest.approx(1.0)
    assert m.ndcg_at_k([["b", "c"]], ["a"], 3) == 0.0


def test_risk_coverage_keeps_the_confident_cases() -> None:
    confidence = [0.9, 0.8, 0.7, 0.6]
    correct = [True, True, False, False]
    curve = m.risk_coverage(confidence, correct, points=(0.5, 1.0))
    assert curve["points"] == [{"coverage": 0.5, "risk": 0.0}, {"coverage": 1.0, "risk": 0.5}]
    assert curve["aurc"] == pytest.approx((0 + 0 + 1 / 3 + 0.5) / 4, abs=1e-4)


def test_retrieval_ranks() -> None:
    ranked = [["a", "b", "c"], ["b", "a"], ["c"]]
    wanted = ["a", "a", "a"]
    assert m.recall_at_k(ranked, wanted, 1) == pytest.approx(1 / 3)
    assert m.recall_at_k(ranked, wanted, 3) == pytest.approx(2 / 3)
    assert m.mean_reciprocal_rank(ranked, wanted) == pytest.approx((1 + 0.5 + 0) / 3)


def test_keyword_baseline_takes_the_most_severe_category() -> None:
    def window(**hits: int) -> WindowFeatures:
        return WindowFeatures(
            n_events=100,
            n_templates=5,
            duration_s=600,
            events_per_min=10,
            error_events=0,
            error_ratio=0,
            keyword_hits=hits,
            burst_score=0,
            peak_errors_per_min=0,
            distinct_nodes=1,
            error_nodes=0,
            node_spread=0,
            novel_templates=0,
            novel_error_templates=0,
            max_component_criticality=0,
            persistence_s=0,
        )

    assert sv.keyword_severity(window(crash=3, network=9)) == "SEV1"
    assert sv.keyword_severity(window(crash=2, unavailable=4)) == "SEV2"  # two crash lines: noise
    assert sv.keyword_severity(window(network=5)) == "SEV3"
    assert sv.keyword_severity(window(degradation=50)) == "SEV4"


def test_grouping_accuracy_needs_exact_groups() -> None:
    truth = ["E1", "E1", "E2", "E2"]
    assert ps.grouping_accuracy(["a", "a", "b", "b"], truth) == 1.0
    assert ps.grouping_accuracy(["a", "a", "a", "b"], truth) == 0.0  # E1 merged into E2's lines
    assert ps.grouping_accuracy(["a", "b", "c", "c"], truth) == 0.5  # E1 split, E2 right
    assert ps.grouping_accuracy(["a", "a", ps.QUARANTINED, "b"], truth) == 0.5


def test_parsing_suite_scores_every_downloaded_sample() -> None:
    summary = ps.summarize(FIXTURES)
    assert summary["n_systems"] >= 10
    assert 0.0 < summary["mean_grouping_accuracy"] <= 1.0
    assert summary["real_lines_flagged_as_injection"] == 0
    assert ps.system_accuracy(FIXTURES / "Missing", "hdfs") is None


def test_edge_suite_parses_everything_and_quarantines_attacks() -> None:
    inputs = ed.generate(n_attacks=110, n_benign=90, seed=5)
    assert {i.family for i in inputs if i.kind == "attack"} == set(ed.ATTACKS)
    result = ed.evaluate(inputs)
    assert result["parser_errors"] == 0
    assert result["attack_recall"] >= 0.9
    assert result["benign_false_positive_rate"] <= 0.02
    assert set(result["recall_by_family"]) == set(ed.ATTACKS)


def test_provider_stats_price_only_what_is_priced() -> None:
    case = _pipeline_case("block_serve_exceptions", supported=True)
    case.llm_calls_detail = [
        {
            "provider": "nim",
            "model": "m",
            "latency_ms": 1000,
            "input_tokens": 10,
            "output_tokens": 5,
            "cost_usd": None,
        },
        {"provider": "nim", "model": "m", "latency_ms": 3000, "error": "timeout"},
        {
            "provider": "azure",
            "model": "g",
            "latency_ms": 500,
            "input_tokens": 4,
            "output_tokens": 2,
            "cost_usd": 0.001,
        },
    ]
    stats = pl.provider_stats([case])
    assert stats["nim"]["calls"] == 2
    assert stats["nim"]["failures"] == 1
    assert stats["nim"]["tokens_in"] == 10
    assert stats["nim"]["cost_usd"] is None
    assert stats["azure"]["cost_usd"] == pytest.approx(0.001)


# --- gate, sampling and saving -----------------------------------------------------------------


def test_gate_reports_each_missed_bound(tmp_path: Path) -> None:
    spec = tmp_path / "thresholds.yaml"
    spec.write_text(
        "smoke:\n  a.score: {min: 0.5}\n  a.misses: {max: 0}\n  a.absent: {min: 1}\n",
        encoding="utf-8",
    )
    passing = {"a": {"score": 0.9, "misses": 0, "absent": 1}}
    assert ev.check_gate(passing, "smoke", spec) == []
    failing = {"a": {"score": 0.4, "misses": 2}}
    failures = ev.check_gate(failing, "smoke", spec)
    assert failures == [
        "a.score = 0.4 is below 0.5",
        "a.misses = 2 is above 0",
        "a.absent: missing from the results",
    ]


def test_gate_refuses_results_from_the_test_fixtures(tmp_path: Path) -> None:
    spec = tmp_path / "thresholds.yaml"
    spec.write_text("smoke: {}\n", encoding="utf-8")
    assert ev.is_fixtures(FIXTURES)
    failures = ev.check_gate({"data": {"fixtures": True}}, "smoke", spec)
    assert len(failures) == 1
    assert "make data" in failures[0]


def test_sample_covers_every_failure_mode_before_repeating(builder: ScenarioBuilder) -> None:
    scenarios = builder.suite(seed=41, per_mode=2, quiet_per_system=1)
    modes = {f"{s.system}.{s.failure_mode}" for s in scenarios}
    picked = ev.sample(scenarios, len(modes))
    assert {f"{s.system}.{s.failure_mode}" for s in picked} == modes
    assert [s.id for s in ev.sample(scenarios, 5)] == [s.id for s in ev.sample(scenarios, 5)]


def test_results_are_saved_per_suite_and_mode(tmp_path: Path) -> None:
    path = ev.save({"suite": "pipeline", "llm": True, "x": 1}, tmp_path)
    assert path.name == "pipeline-llm.json"
    assert json.loads(path.read_text())["x"] == 1


# --- attacks and stage timing ------------------------------------------------------------------


def test_poisoned_windows_hide_attacks_in_the_systems_own_format(builder: ScenarioBuilder) -> None:
    scenario = builder.build("hdfs.block_serve_exceptions", seed=2, nodes=3)
    lines = pl.poison(scenario)
    assert len(lines) == len(scenario.lines) + len(pl.ATTACKS)
    out = parse_lines(lines, system="hdfs", guard=GuardrailConfig(), evidence=EvidenceStore())
    assert len(out.batch.guard.injections) == len(pl.ATTACKS)
    assert len(out.lines) == len(scenario.lines)  # quarantined lines are never analysed


def test_stage_durations_sum_repeated_nodes() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)

    def event(seq: int, kind: EventKind, node: str, ms: int) -> RunEvent:
        return RunEvent(
            seq=seq, run_id="r", kind=kind, node=node, ts=t0 + timedelta(milliseconds=ms)
        )

    events = [
        event(0, "node_started", "investigate", 0),
        event(1, "node_finished", "investigate", 100),
        event(2, "node_started", "investigate", 200),
        event(3, "node_finished", "investigate", 250),
        event(4, "node_started", "review", 300),
        event(5, "interrupt", "review", 310),
    ]
    assert pl.stage_durations(events) == {"investigate": 150.0, "review": 10.0}


# --- report ------------------------------------------------------------------------------------


def _severity_case(truth: str, aria: str, *, review: bool = False) -> sv.SeverityCase:
    return sv.SeverityCase(
        id=f"scn-{truth}-{aria}",
        system="hdfs",
        failure_mode="block_serve_exceptions",
        truth=truth,
        label_source="policy",
        keyword=aria,
        rules=aria,
        model=aria,
        model_floored=aria,
        aria=aria,
        decided_by="model" if not review else "fallback",
        needs_review=review,
        probabilities={aria: 0.9, truth: 0.1} if aria != truth else {aria: 1.0},
        prediction_set=[aria, truth],
        raw_set=[aria],
    )


def _pipeline_case(mode: str, *, supported: bool) -> pl.PipelineCase:
    return pl.PipelineCase(
        id=f"scn-{mode}",
        system="hdfs",
        failure_mode=mode,
        truth="SEV3",
        benign=False,
        status="awaiting_review",
        severity="SEV3",
        decided_by="rules",
        valid=True,
        all_cited=True,
        citation_coverage=1.0,
        generated_by="template",
        retrieved_modes=[mode],
        leading_mode=mode if supported else None,
        supported=supported,
        replans=0,
        seconds=0.5,
        stages_ms={"parse_shard": 10.0, "review": 2.0},
        llm_calls=0,
        tool_calls=5,
        tokens=0,
        exhausted=[],
    )


def test_report_states_provenance_results_and_limitations() -> None:
    cases = [
        _severity_case("SEV1", "SEV1"),
        _severity_case("SEV2", "SEV1", review=True),
        _severity_case("SEV3", "SEV3"),
        _severity_case("SEV4", "SEV4"),
    ]
    runs = [
        _pipeline_case("block_serve_exceptions", supported=True),
        _pipeline_case("none", supported=False),
    ]
    results: dict[str, Any] = {
        "created_at": "2026-10-29T00:00:00+00:00",
        "git_sha": "abc1234",
        "data": {"test_seeds": [41, 42], "fixtures": False},
        "severity": sv.summarize(cases, alpha=0.1, majority="SEV3"),
        "pipeline": pl.summarize(runs, budget_tokens=60_000),
        "parsing": ps.summarize(FIXTURES),
        "edge": ed.evaluate(ed.generate(n_attacks=22, n_benign=10)),
        "robustness": pl.summarize_robustness(
            [
                {
                    "severity_unchanged": True,
                    "tool_calls_unchanged": True,
                    "quarantined": 3,
                    "expected_quarantined": 3,
                    "leaked_markers": [],
                }
            ]
        ),
    }
    text = report.render(results)
    assert "semi-synthetic" in text
    assert "## Severity" in text
    assert "## End to end (offline: no LLM steps)" in text
    assert "## Prompt-injection robustness" in text
    assert "## Limitations" in text
    assert "## Log parsing" in text
    assert "## Edge cases and prompt injection" in text
    assert "Keyword categories only" in text
    assert "Risk–coverage" in text
    assert "nDCG@3" in text
    assert "False alarms: 0.0% of 1 quiet windows" in text
    assert "test fixtures" not in text
    flagged = report.render({**results, "data": {**results["data"], "fixtures": True}})
    assert "test fixtures" in flagged


@pytest.mark.slow
async def test_smoke_suite_runs_end_to_end_on_the_fixtures() -> None:
    results = await ev.run("smoke", loghub_dir=FIXTURES, limit=1)
    assert results["data"]["fixtures"]
    assert results["data"]["synthetic"]
    pipeline = results["pipeline"]
    assert pipeline["groundedness"]["valid_reports"] == 1.0
    assert pipeline["groundedness"]["every_claim_cited"] == 1.0
    robustness = results["robustness"]
    assert robustness["severity_invariant"] == 1.0
    assert robustness["tool_use_invariant"] == 1.0
    assert robustness["reports_with_injected_text"] == 0
    assert ev.check_gate(results, "smoke")[0].startswith("the thresholds are set on")
