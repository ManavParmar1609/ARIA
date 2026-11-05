"""Per-level prediction sets, the severe-miss guard and calibration for new systems."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from aria.contracts.base import SEVERITY_ORDER, Severity
from aria.contracts.parsing import WindowFeatures
from aria.evidence import EvidenceStore
from aria.severity.conformal import FAMILIAR, choose_guard, fit_calibration, level_alphas
from aria.severity.engine import SeverityEngine
from aria.severity.features import log_feature_names
from aria.severity.model import Calibration, LinearModel, Novelty, level_threshold, softmax
from aria.severity.policy import coverage_words
from aria.severity.rules import load_rules

CLASSES = [str(s) for s in SEVERITY_ORDER]
RULES = Path("config/severity_rules.yaml")


def _calibration(
    thresholds: dict[str, float], *, guard: float | None = None, ordered: bool = True
) -> Calibration:
    """A calibration whose threshold for each level is exactly the one given."""
    return Calibration(
        temperature=1.0,
        alphas=dict.fromkeys(CLASSES, 0.5),
        # One score per level at alpha 0.5: the threshold is that score.
        scores={cls: [thresholds[cls]] for cls in CLASSES},
        guard_classes=["SEV1", "SEV2"],
        guard=guard,
        epsilon=None if guard is None else 0.05,
        ordered=ordered,
    )


def test_a_level_threshold_is_the_corrected_quantile_or_never_rules_the_level_out() -> None:
    scores = [i / 100 for i in range(1, 34)]  # 33 windows of one level
    assert level_threshold(scores, 0.05) == scores[-1]  # ceil(34 x 0.95) = 33: the largest
    assert level_threshold(scores, 0.10) == scores[30]  # ceil(34 x 0.90) = 31
    assert level_threshold(scores[:18], 0.05) == 1.0  # 18 windows cannot promise 95%
    assert level_threshold([], 0.1) == 1.0


def test_each_level_keeps_its_promise_on_exchangeable_data() -> None:
    """Over many draws, a level stays in the set at least 1 - alpha of the time."""
    rng = np.random.default_rng(3)
    kept = []
    for _ in range(2_000):
        calibration = sorted(rng.random(40).tolist())
        kept.append(rng.random() <= level_threshold(calibration, 0.05))
    assert np.mean(kept) >= 0.95 - 0.01  # exact level: ceil(41 x 0.95) / 41 = 0.951


def test_ordered_sets_fill_the_gap_between_their_extremes() -> None:
    calibration = _calibration({"SEV1": 0.8, "SEV2": 0.1, "SEV3": 0.8, "SEV4": 0.1})
    probs = np.array([0.3, 0.1, 0.5, 0.1])  # SEV1 and SEV3 clear their bars, SEV2 does not
    assert calibration.classes_in(probs, CLASSES) == ["SEV1", "SEV2", "SEV3"]
    unordered = _calibration({"SEV1": 0.8, "SEV2": 0.1, "SEV3": 0.8, "SEV4": 0.1}, ordered=False)
    assert unordered.classes_in(probs, CLASSES) == ["SEV1", "SEV3"]


def test_an_empty_set_stays_empty_so_the_engine_can_say_it_does_not_know() -> None:
    calibration = _calibration(dict.fromkeys(CLASSES, 0.05))
    assert calibration.classes_in(np.array([0.25, 0.25, 0.25, 0.25]), CLASSES) == []


def test_the_guard_adds_the_likelier_serious_level_when_serious_mass_is_high() -> None:
    calibration = _calibration({"SEV1": 0.1, "SEV2": 0.1, "SEV3": 0.6, "SEV4": 0.1}, guard=0.3)
    probs = np.array([0.1, 0.25, 0.6, 0.05])  # serious mass 0.35, neither serious level clears
    assert calibration.classes_in(probs, CLASSES) == ["SEV2", "SEV3"]
    calm = np.array([0.05, 0.1, 0.8, 0.05])  # serious mass 0.15: below the guard
    assert calibration.classes_in(calm, CLASSES) == ["SEV3"]


def _guard_case() -> tuple[np.ndarray, list[str], Calibration]:
    rng = np.random.default_rng(7)
    logits = rng.normal(size=(400, 4)) * 1.5
    probs = softmax(logits)
    truth = [CLASSES[rng.choice(4, p=p)] for p in probs]
    base = Calibration(
        temperature=1.0,
        alphas=dict.fromkeys(CLASSES, 0.3),  # loose thresholds: plenty of severe misses
        scores={
            cls: sorted(1 - probs[i, k] for i, t in enumerate(truth) if t == cls)
            for k, cls in enumerate(CLASSES)
        },
        guard_classes=["SEV1", "SEV2"],
        ordered=True,
    )
    return probs, truth, base


def _severe_misses(probs: np.ndarray, truth: list[str], calibration: Calibration) -> int:
    return sum(
        1
        for p, t in zip(probs, truth, strict=True)
        if t in ("SEV1", "SEV2") and not set(calibration.classes_in(p, CLASSES)) & {"SEV1", "SEV2"}
    )


@pytest.mark.parametrize("epsilon", [0.02, 0.05, 0.1])
def test_the_guard_is_the_loosest_that_certifies_the_severe_miss_risk(epsilon: float) -> None:
    probs, truth, base = _guard_case()
    n = sum(t in ("SEV1", "SEV2") for t in truth)
    guard, certified = choose_guard(probs, truth, CLASSES, base, epsilon)
    assert certified == epsilon
    assert guard is not None  # these loose sets miss too often without one
    base.guard = guard
    assert (_severe_misses(probs, truth, base) + 1) / (n + 1) <= epsilon
    base.guard = guard + 1e-6  # any looser guard breaks the bound
    assert (_severe_misses(probs, truth, base) + 1) / (n + 1) > epsilon


def test_too_few_serious_windows_certify_nothing() -> None:
    probs, truth, base = _guard_case()
    keep = [i for i, t in enumerate(truth) if t not in ("SEV1", "SEV2")]
    keep += [i for i, t in enumerate(truth) if t in ("SEV1", "SEV2")][:10]
    picked = [truth[i] for i in keep]
    assert choose_guard(probs[keep], picked, CLASSES, base, 0.05) == (None, None)


def test_a_calibration_that_already_meets_the_target_needs_no_guard() -> None:
    probs, truth, base = _guard_case()
    base.alphas = dict.fromkeys(CLASSES, 0.01)  # sets so wide nothing serious is missed
    assert choose_guard(probs, truth, CLASSES, base, 0.05) == (None, 0.05)


def test_fitting_gives_serious_levels_their_tighter_miss_rate() -> None:
    rng = np.random.default_rng(11)
    logits = rng.normal(size=(600, 4)) * 2
    truth = [CLASSES[rng.choice(4, p=p)] for p in softmax(logits)]
    alphas = level_alphas(CLASSES, 0.1, 0.05)
    assert alphas == {"SEV1": 0.05, "SEV2": 0.05, "SEV3": 0.1, "SEV4": 0.1}
    calibration = fit_calibration(
        logits[:200],
        truth[:200],
        logits[200:],
        truth[200:],
        CLASSES,
        alphas=alphas,
        epsilon=0.05,
        source="test",
    )
    assert calibration.temperature == pytest.approx(1.0, rel=0.25)
    assert calibration.ordered
    for cls in CLASSES:
        n = len(calibration.scores[cls])
        k = math.ceil((n + 1) * (1 - alphas[cls]))
        assert calibration.threshold(cls) == calibration.scores[cls][k - 1]
    assert calibration.epsilon == 0.05


@given(st.lists(st.floats(0.01, 1.0), min_size=4, max_size=4), st.floats(0.0, 1.0))
def test_a_set_is_always_a_contiguous_run_of_levels(weights: list[float], guard: float) -> None:
    probs = np.array(weights) / sum(weights)
    calibration = _calibration({"SEV1": 0.6, "SEV2": 0.2, "SEV3": 0.9, "SEV4": 0.3}, guard=guard)
    chosen = calibration.classes_in(probs, CLASSES)
    positions = [CLASSES.index(c) for c in chosen]
    assert positions == list(range(positions[0], positions[-1] + 1)) if positions else True


def _model(calibrations: dict[str, Calibration], systems: list[str]) -> LinearModel:
    names = log_feature_names()
    return LinearModel(
        name="test",
        classes=CLASSES,
        feature_names=names,
        mean=np.zeros(len(names)),
        scale=np.full(len(names), 100.0),
        coef=np.zeros((4, len(names))),
        intercept=np.log(np.array([0.05, 0.3, 0.6, 0.05])),
        conformal_q=0.5,
        version="test-model",
        metadata={"trained_systems": systems},
        calibrations=calibrations,
    )


def test_a_model_round_trips_its_calibrations(tmp_path: Path) -> None:
    familiar = _calibration({"SEV1": 0.2, "SEV2": 0.5, "SEV3": 0.7, "SEV4": 0.2}, guard=0.4)
    model = _model({FAMILIAR: familiar}, ["hdfs"])
    path = tmp_path / "m.json"
    model.save(path)
    loaded = LinearModel.load(path)
    assert loaded.calibrations[FAMILIAR].to_dict() == familiar.to_dict()
    raw = model.to_dict()
    raw["calibrations"][FAMILIAR]["alphas"] = {"P1": 0.1}
    with pytest.raises(ValueError, match="do not match"):
        LinearModel.from_dict(raw)


def _window() -> WindowFeatures:
    return WindowFeatures(
        n_events=600,
        n_templates=12,
        duration_s=1_200.0,
        events_per_min=30.0,
        level_counts={"INFO": 560, "ERROR": 40},
        error_events=40,
        error_ratio=40 / 600,
        keyword_hits={},
        burst_score=0.0,
        peak_errors_per_min=2.0,
        distinct_nodes=4,
        error_nodes=1,
        node_spread=0.25,
        novel_templates=0,
        novel_error_templates=0,
        components=["APP"],
        critical_components=[],
        max_component_criticality=0.0,
        persistence_s=0.0,
    )


def test_a_system_the_model_never_trained_on_goes_to_a_person() -> None:
    sure = _calibration({"SEV1": 0.1, "SEV2": 0.1, "SEV3": 0.6, "SEV4": 0.1})
    model = _model({FAMILIAR: sure}, ["hdfs"])
    model.intercept = np.log(np.array([0.01, 0.02, 0.95, 0.02]))
    engine = SeverityEngine(load_rules(RULES), model, alpha=0.1)
    assert engine.trained_on("HDFS")
    assert not engine.trained_on("generic")
    familiar = engine.preliminary(_window(), system="hdfs", evidence=EvidenceStore())
    new = engine.preliminary(_window(), system="generic", evidence=EvidenceStore())
    assert familiar.prediction_set == new.prediction_set == [Severity.SEV3]
    assert familiar.auto_decision(0.85) is not None
    assert "new_system" in new.novelty
    assert new.auto_decision(0.85) is None  # confident, but a person confirms
    unlisted = SeverityEngine(load_rules(RULES), _model({FAMILIAR: sure}, []), alpha=0.1)
    assert unlisted.trained_on("generic")  # an older file that never listed its systems


def test_an_unusual_window_keeps_the_levels_the_rules_leave_open() -> None:
    sure = _calibration({"SEV1": 0.1, "SEV2": 0.1, "SEV3": 0.6, "SEV4": 0.1})
    model = _model({FAMILIAR: sure}, ["hdfs"])
    names = log_feature_names()
    model.novelty = Novelty(
        center=np.zeros(len(names)),
        precision=np.eye(len(names)),
        distances=[0.001] * 200,  # every held-out window sat right at the centre
        shares=[0.0] * 200,
    )
    engine = SeverityEngine(load_rules(RULES), model, alpha=0.1)
    pre = engine.preliminary(_window(), system="hdfs", evidence=EvidenceStore())
    assert "unusual_mix" in pre.novelty
    assert pre.auto_decision(0.85) is None
    assert pre.rule_severity in pre.prediction_set


def test_a_novelty_p_value_is_the_share_of_held_out_windows_as_far_out() -> None:
    stats = Novelty(
        center=np.zeros(2),
        precision=np.eye(2),
        distances=[0.5, 1.0, 1.5, 2.0],
        shares=[0.0, 0.1, 0.2, 0.9],
    )
    assert stats.p_value(np.array([0.0, 0.0])) == pytest.approx(5 / 5)
    assert stats.p_value(np.array([1.5, 0.0])) == pytest.approx(3 / 5)  # 1.5 and 2.0, plus one
    assert stats.p_value(np.array([3.0, 4.0])) == pytest.approx(1 / 5)  # beyond every one
    assert stats.share_p_value(1.0) == pytest.approx(1 / 5)
    raw = stats.to_dict()
    assert Novelty.from_dict(raw, 2).to_dict() == raw
    with pytest.raises(ValueError, match="do not match"):
        Novelty.from_dict(raw, 3)


def test_the_set_says_what_it_promises_per_level() -> None:
    alphas = {Severity(c): a for c, a in level_alphas(CLASSES, 0.1, 0.05).items()}
    words = coverage_words(alphas)
    assert words == "prediction set (95% coverage for SEV1 and SEV2, 90% for SEV3 and SEV4)"
    assert coverage_words(dict.fromkeys(SEVERITY_ORDER, 0.1)) == "90% prediction set"
