"""The model's choice inside the prediction set: the harness, offline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from aria.config import get_app_config
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.evals import llm_choice as lc
from aria.evals import report, rings
from aria.evals import run as runs
from aria.evals import severity as sv
from aria.severity.engine import SeverityEngine
from aria.severity.rules import load_rules
from aria.severity.training import known_templates

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"


@pytest.fixture(scope="module")
def builder() -> ScenarioBuilder:
    return ScenarioBuilder(LinePools.from_loghub(FIXTURES))


@pytest.mark.slow
async def test_offline_the_fake_is_asked_k_times_on_every_window_the_policy_leaves_open(
    builder: ScenarioBuilder,
) -> None:
    config = get_app_config().severity
    rules = load_rules(Path(config.rules_file))
    test = sv.held_out(builder, seeds=(41,), per_mode=1, quiet_per_system=1)
    features = sv.featurize(builder, test)
    windows = rings.training_windows(builder, rules, per_mode=1, quiet_per_system=1)
    cases = await lc.held_out_systems(
        rules, test, features, windows, config=config, router=lc.offline_router(), k=2
    )
    assert cases, "the fixtures leave some windows to a model"
    assert len(cases) <= len(test)  # the windows the policy decided alone were never asked
    for case in cases:
        assert case.source == "held_out_system"
        assert len(case.choices) == 2
        assert all(choice in case.prediction_set for choice in case.choices)
        assert case.choices[0] == case.model_top  # the fake picks the calibrated top level
        assert case.providers == ["fake", "fake"]
        assert case.most_severe == case.prediction_set[0]
    summary = lc.summarize(cases, k=2)
    assert summary["windows"] == summary["answered"] == len(cases)
    assert summary["calls"] == 2 * len(cases)
    assert summary["answered_by"] == {"fake": 2 * len(cases)}
    assert summary["override"]["windows"] == 0
    assert summary["methods"]["model_pick"] == summary["methods"]["calibrated_top"]
    assert summary["consistency"]["same_level_every_run"]["rate"] == 1.0
    assert set(summary["by_group"]) <= {s.system for s in test}


def _case(
    case_id: str,
    truth: str,
    prediction_set: list[str],
    top: str,
    choices: list[str | None],
    *,
    group: str = "hdfs",
    reasons: list[str] | None = None,
) -> lc.ChoiceCase:
    return lc.ChoiceCase(
        id=case_id,
        source="held_out_system" if group != "bgl" else "bgl",
        group=group,
        truth=truth,
        prediction_set=prediction_set,
        model_top=top,
        most_severe=prediction_set[0],
        choices=choices,
        reasons=reasons or [],
        providers=["llm"] * sum(1 for c in choices if c),
    )


CASES = [
    # An override that put the window right, the same on every run.
    _case("a", "SEV2", ["SEV1", "SEV2"], "SEV1", ["SEV2", "SEV2", "SEV2"]),
    # An override that put it wrong on the first run, right on the others.
    _case("b", "SEV1", ["SEV1", "SEV2"], "SEV1", ["SEV2", "SEV1", "SEV1"]),
    # One level in the set, one run with no accepted answer.
    _case(
        "c",
        "SEV3",
        ["SEV3"],
        "SEV3",
        ["SEV3", None, "SEV3"],
        group="bgl",
        reasons=["the models were at their limits"],
    ),
    # No answer at all.
    _case(
        "d",
        "SEV2",
        ["SEV2", "SEV3"],
        "SEV2",
        [None, None, None],
        group="bgl",
        reasons=["no LLM adjudicator is configured"] * 3,
    ),
]


def test_the_summary_counts_overrides_and_consistency() -> None:
    s = lc.summarize(CASES, k=3)
    assert (s["windows"], s["answered"], s["contested"], s["calls"]) == (4, 3, 3, 12)
    assert s["unanswered"] == {"no LLM adjudicator is configured": 1}
    assert s["coverage"] == 1.0
    assert s["labels"] == {"SEV1": 1, "SEV2": 2, "SEV3": 1}
    # The pick: a right, b wrong, c right. The calibrated top: a wrong, b right, c right.
    assert s["methods"]["model_pick"]["accuracy"] == round(2 / 3, 4)
    assert s["methods"]["calibrated_top"]["accuracy"] == round(2 / 3, 4)
    assert s["methods"]["model_pick"]["severe"] == {
        "misses": 0,
        "severe": 2,
        "rate": 0.0,
        "upper95": s["methods"]["model_pick"]["severe"]["upper95"],
    }
    override = s["override"]
    assert (override["windows"], override["put_right"], override["put_wrong"]) == (2, 1, 1)
    assert override["net"] == 0
    assert override["against_calibrated_top"]["right_only_a"] == 1
    assert override["against_calibrated_top"]["right_only_b"] == 1
    consistency = s["consistency"]
    assert consistency["complete"] == 2  # a and b had three accepted answers
    assert consistency["same_level_every_run"]["hits"] == 1
    assert consistency["right_every_run"]["hits"] == 1  # pass^3: only a
    assert consistency["right_in_any_run"]["hits"] == 2  # pass@3: a and b
    assert s["by_group"]["hdfs"]["overrides"] == 2
    assert s["by_group"]["bgl"] == {
        "windows": 2,
        "answered": 1,
        "pick_accuracy": 1.0,
        "top_accuracy": 1.0,
        "overrides": 0,
    }


def _bgl_line(tag: str, ts: datetime, node: str, level: str, message: str) -> str:
    stamp = ts.strftime("%Y-%m-%d-%H.%M.%S.%f")
    return (
        f"{tag} {int(ts.timestamp())} {ts:%Y.%m.%d} {node} {stamp} {node} RAS KERNEL {level} "
        f"{message}".rstrip()
    )


@pytest.mark.slow
async def test_bgl_windows_are_sampled_from_those_the_policy_leaves_open(
    tmp_path: Path, builder: ScenarioBuilder
) -> None:
    start = datetime(2005, 6, 3, 15, 0, tzinfo=UTC)
    lines = [
        _bgl_line(
            "-",
            start + timedelta(seconds=20 * i),
            f"R0{i % 4}-M0-N0",
            "INFO",
            "instruction cache parity error corrected",
        )
        for i in range(30)
    ]
    later = start + timedelta(minutes=40)
    lines += [
        _bgl_line(
            "KERNRTSP",
            later + timedelta(seconds=10 * i),
            f"R1{i % 6}-M0-N0",
            "FATAL",
            "rts panic! - stopping execution",
        )
        for i in range(30)
    ]
    (tmp_path / "BGL.log").write_text("\n".join(lines) + "\n")
    config = get_app_config().severity
    rules = load_rules(Path(config.rules_file))
    windows = rings.training_windows(builder, rules, per_mode=1, quiet_per_system=1)
    unseen = SeverityEngine(
        rules,
        rings.model_without(
            windows,
            lambda w: bool(w.system != "bgl"),
            alpha=config.alpha,
            rules_version=rules.version,
            serious_alpha=config.serious_alpha,
            severe_miss_risk=config.severe_miss_risk,
        ),
        alpha=config.alpha,
    )
    cases, left_open = await lc.bgl_windows(
        tmp_path / "BGL.log",
        engine=unseen,
        known=known_templates(builder, "bgl"),
        pool={"instruction cache parity error corrected"},
        router=lc.offline_router(),
        k=2,
        windows=1,
    )
    assert 0 <= left_open <= 2
    assert len(cases) == min(1, left_open)
    for case in cases:
        assert (case.source, case.group) == ("bgl", "bgl")
        assert case.truth in {"SEV1", "SEV4"}
        assert len(case.choices) == 2
        assert all(choice in case.prediction_set for choice in case.choices)


def test_the_report_quotes_the_choice_only_from_a_live_run() -> None:
    results: dict[str, Any] = {
        "created_at": "2026-11-04T00:00:00+00:00",
        "git_sha": "abc1234",
        "data": {"test_seeds": [41, 42], "fixtures": False},
    }
    assert "The model's choice inside the set" not in report.render(results)
    live = {
        "created_at": "2026-11-04T01:00:00+00:00",
        "git_sha": "def5678",
        "llm_choice": {
            "k": 3,
            "calls": 12,
            "model": "the configured chain",
            "held_out_systems": lc.summarize(CASES, k=3),
            "bgl": {"missing": "download it with: aria data download --source loghub-bgl"},
        },
    }
    text = report.render(results, choice=live)
    assert "## The model's choice inside the set" in text
    assert "### Systems the model never saw" in text
    assert "pass^3" in text
    assert "1 put right, 1 put wrong (net +0" in text
    assert "The BGL log was not downloaded" in text
    assert "llm (8) answered" in text  # the accepted answers among the cases


def test_the_choice_is_a_suite_of_its_own() -> None:
    assert "llm-choice" in runs.SUITES
    assert runs.SUITES.index("llm-choice") < runs.SUITES.index("all")
