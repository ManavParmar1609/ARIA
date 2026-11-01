"""Systems and failure modes ARIA has never seen (evals/rings.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aria.contracts.base import Severity
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.evals import report, rings
from aria.evals import severity as sv
from aria.evals.severity import SeverityCase
from aria.severity.rules import load_rules
from aria.severity.training import LabelledWindow

FIXTURES = Path("tests/fixtures/loghub")
RULES = Path("config/severity_rules.yaml")


def _case(i: int, truth: str, aria: str, *, review: bool = False) -> SeverityCase:
    return SeverityCase(
        id=f"w{i}",
        system="x",
        failure_mode="m",
        truth=truth,
        label_source="policy",
        keyword="SEV4",
        rules=aria,
        model=aria,
        model_floored=aria,
        aria=aria,
        decided_by="policy",
        needs_review=review,
        probabilities={"SEV1": 0.1, "SEV2": 0.2, "SEV3": 0.3, "SEV4": 0.4},
        prediction_set=[aria],
        raw_set=[aria],
    )


def test_a_ring_reports_severe_misses_with_an_exact_bound() -> None:
    ring = rings.Ring("leave_one_system_out")
    pairs = [
        ("SEV1", "SEV1"),
        ("SEV2", "SEV3"),
        ("SEV2", "SEV2"),
        ("SEV4", "SEV4"),
        ("SEV3", "SEV2"),
    ]
    for i, (truth, aria) in enumerate(pairs):
        ring.cases.append(
            rings.HeldOut("a" if i < 3 else "b", _case(i, truth, aria, review=i == 4))
        )
    summary = rings.summarize_ring(ring, alpha=0.1)
    assert summary["severe"]["misses"] == 1
    assert summary["severe"]["severe"] == 3
    assert summary["severe"]["upper95"] > 1 / 3  # one miss in three supports a weak claim only
    assert summary["over_triage"]["hits"] == 1
    assert summary["deferred"]["hits"] == 1
    assert summary["spread"]["groups_with_a_severe_miss"] == ["a"]
    assert set(summary["methods"]) == {"aria_policy", "rules_only", "model_only", "novelty_only"}


def _window(i: int, novelty: float, severity: Severity) -> LabelledWindow:
    return LabelledWindow(
        id=f"t{i}",
        system="x",
        failure_mode="m",
        severity=severity,
        values={"novel_templates": novelty * 10, "n_templates": 10.0},
        rules=None,  # type: ignore[arg-type]  # the cut search reads values only
        synthetic=True,
        label_source="policy",
    )


def test_the_novelty_baseline_learns_cut_points_from_training_only() -> None:
    windows = [
        *[_window(i, 0.9, Severity.SEV1) for i in range(5)],
        *[_window(10 + i, 0.6, Severity.SEV2) for i in range(5)],
        *[_window(20 + i, 0.3, Severity.SEV3) for i in range(5)],
        *[_window(30 + i, 0.0, Severity.SEV4) for i in range(5)],
    ]
    cuts = rings.fit_novelty_cuts(windows)
    assert len(cuts) == 3
    assert cuts[0] >= cuts[1] >= cuts[2]
    assert rings._novelty_level(0.95, cuts) == "SEV1"
    assert rings._novelty_level(0.0, cuts) == "SEV4"


def test_the_report_states_the_held_out_results_and_the_tuning_record() -> None:
    ring = rings.Ring("leave_one_system_out")
    for i, (truth, aria) in enumerate([("SEV1", "SEV1"), ("SEV2", "SEV3"), ("SEV4", "SEV4")]):
        ring.cases.append(rings.HeldOut("hdfs" if i < 2 else "bgl", _case(i, truth, aria)))
    summary = rings.summarize_ring(ring, alpha=0.1)
    text = "\n".join(
        report._generalisation(
            {"leave_one_system_out": summary, "leave_one_failure_mode_out": {"n": 0}}
        )
    )
    assert "## Systems and failures ARIA has never seen" in text
    assert "1 of 2 (at most" in text
    assert "| hdfs |" in text
    record = "\n".join(
        report._registry({"suites": {"real.bgl": {"ring": "C", "status": "seen", "note": "n"}}})
    )
    assert "| real.bgl | C | Looked at | n |" in record


@pytest.mark.slow
def test_every_held_out_window_is_rated_by_a_model_that_never_saw_its_system() -> None:
    builder = ScenarioBuilder(LinePools.from_loghub(FIXTURES))
    rules = load_rules(RULES)
    test = sv.held_out(builder, seeds=(41,), per_mode=1, quiet_per_system=1)
    features = sv.featurize(builder, test)
    windows = rings.training_windows(builder, rules, per_mode=1, quiet_per_system=1)
    ring = rings.hold_out(
        "leave_one_system_out",
        test,
        features,
        windows,
        rules,
        alpha=0.1,
        scenario_group=lambda s: s.system,
        window_group=lambda w: w.system,
    )
    assert {h.case.system for h in ring.cases} == {s.system for s in test}
    for held in ring.cases:
        fold = ring.groups[held.group]
        assert held.case.system == held.group
        # Fitted on every training window except the held-out system's.
        assert fold["n_train"] == sum(1 for w in windows.train if w.system != held.group)
