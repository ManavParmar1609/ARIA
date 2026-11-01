"""Recalibrating the severity model on reviewed incidents: the active-learning loop."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from aria.config import SeverityConfig
from aria.contracts.inputs import TriageRequest
from aria.contracts.run import RunStatus
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db
from aria.graph.runner import TriageRunner
from aria.services import Services
from aria.severity import recalibration
from aria.severity.conformal import FAMILIAR
from aria.severity.engine import SeverityEngine
from aria.severity.model import Calibration, LinearModel, live_model_path
from aria.severity.recalibration import (
    ACI_STEP,
    BATCH_PER_LEVEL,
    MIN_REVIEWED,
    BlindCheck,
    ReviewedExample,
    adapt,
    adapt_from_blind_checks,
    recalibrate,
    recalibrate_from_feedback,
    reviewed_examples,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
CLASSES = ["SEV1", "SEV2", "SEV3", "SEV4"]


def tiny_model(conformal_q: float) -> LinearModel:
    """One feature: large values point to SEV1, small ones to SEV4."""
    return LinearModel(
        name="tiny",
        classes=CLASSES,
        feature_names=["x"],
        mean=np.array([0.0]),
        scale=np.array([1.0]),
        coef=np.array([[3.0], [1.0], [-1.0], [-3.0]]),
        intercept=np.zeros(4),
        conformal_q=conformal_q,
        version="tiny-1",
    )


def examples(model: LinearModel, n: int, *, disagree: float, seed: int) -> list[ReviewedExample]:
    """Reviews of ``n`` windows; reviewers move ``disagree`` of them one class away."""
    rng = np.random.default_rng(seed)
    out: list[ReviewedExample] = []
    for i in range(n):
        x = float(rng.uniform(-2, 2))
        top = int(np.argmax(model.predict_proba(model.matrix([{"x": x}]))[0]))
        label = top if rng.random() >= disagree else min(3, top + 1) if top < 3 else 2
        out.append(ReviewedExample(i, {"x": x}, CLASSES[label], used=False))
    return out


def test_recalibration_widens_sets_until_reviewed_severities_are_covered() -> None:
    model = tiny_model(conformal_q=0.2)
    reviewed = examples(model, 40, disagree=0.4, seed=1)
    result = recalibrate(model, reviewed, alpha=0.1)

    assert result.coverage_before < 0.9
    assert result.coverage_after >= 0.9  # split-conformal: at least 1 - alpha on its own data
    assert result.threshold_before == 0.2
    assert result.threshold_after > 0.2
    assert result.mean_set_after > result.mean_set_before
    assert result.model.version == "tiny-1-recal40"
    assert result.model.metadata["trained_version"] == "tiny-1"
    assert result.model.metadata["recalibrated_from"] == "tiny-1"
    assert model.conformal_q == 0.2  # the loaded model is left as it was
    assert np.array_equal(result.model.coef, model.coef)  # only the threshold moves

    again = recalibrate(result.model, examples(model, 50, disagree=0.4, seed=2), alpha=0.1)
    assert again.model.version == "tiny-1-recal50"
    assert again.model.metadata["trained_version"] == "tiny-1"


def test_recalibration_narrows_sets_when_reviewers_agree() -> None:
    model = tiny_model(conformal_q=0.95)  # sets of nearly every class
    result = recalibrate(model, examples(model, 40, disagree=0.0, seed=3), alpha=0.1)
    assert result.threshold_after < 0.95
    assert result.mean_set_after < result.mean_set_before
    assert result.coverage_after >= 0.9


def test_an_upgrade_ignores_a_recalibration_of_the_previous_model(tmp_path: Path) -> None:
    """The shared volume kept the last release's recalibrated model, so a retrained model shipped
    in a new release was never used."""
    shipped, shared = tmp_path / "app", tmp_path / "volume"
    shipped.mkdir()
    shared.mkdir()
    trained_file = shipped / "severity_log.json"
    live = live_model_path(trained_file, shared)
    previous = tiny_model(conformal_q=0.2)
    recalibrate(previous, examples(previous, 40, disagree=0.4, seed=1), alpha=0.1).model.save(live)
    retrained = replace(tiny_model(conformal_q=0.5), version="tiny-2")
    retrained.save(trained_file)
    config = SeverityConfig(log_model_file=trained_file)

    engine = SeverityEngine.load(config, models_dir=shared)
    assert engine.model is not None
    assert engine.model.version == "tiny-2"  # not "tiny-1-recal40"
    # A recalibration of this release's model is used, by new and running engines alike.
    current = recalibrate(retrained, examples(retrained, 40, disagree=0.4, seed=2), alpha=0.1)
    current.model.save(live)
    os.utime(live, ns=(time.time_ns(), time.time_ns() + 1_000_000))
    assert engine.refresh()
    assert engine.model.version == "tiny-2-recal40"
    reloaded = SeverityEngine.load(config, models_dir=shared).model
    assert reloaded is not None
    assert reloaded.version == "tiny-2-recal40"


def test_a_checkout_keeps_reloading_its_own_recalibrations(tmp_path: Path) -> None:
    """In a checkout the live model is the shipped file, so after one recalibration the next must
    still be picked up."""
    models = tmp_path / "models"
    models.mkdir()
    path = models / "severity_log.json"
    model = tiny_model(conformal_q=0.2)
    first = recalibrate(model, examples(model, 40, disagree=0.4, seed=1), alpha=0.1).model
    first.save(path)
    engine = SeverityEngine.load(SeverityConfig(log_model_file=path), models_dir=models)
    assert engine.model is not None
    assert engine.model.version == "tiny-1-recal40"
    second = recalibrate(first, examples(model, 50, disagree=0.4, seed=2), alpha=0.1).model
    second.save(path)
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 1_000_000))
    assert engine.refresh()
    assert engine.model.version == "tiny-1-recal50"
    # Nor is a model retrained in place mistaken for a previous release's.
    replace(tiny_model(conformal_q=0.3), version="tiny-2").save(path)
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 2_000_000))
    assert engine.refresh()
    assert engine.model.version == "tiny-2"


def test_after_an_upgrade_reviews_recalibrate_the_new_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The job kept recalibrating the previous release's model, which the engine then refused,
    so reviews never reached the model the upgrade shipped."""
    shipped, shared = tmp_path / "app", tmp_path / "volume"
    shipped.mkdir()
    shared.mkdir()
    trained_file = shipped / "severity_log.json"
    live = live_model_path(trained_file, shared)
    previous = tiny_model(conformal_q=0.2)
    recalibrate(previous, examples(previous, 40, disagree=0.4, seed=1), alpha=0.1).model.save(live)
    replace(tiny_model(conformal_q=0.5), version="tiny-2").save(trained_file)
    engine = SeverityEngine.load(SeverityConfig(log_model_file=trained_file), models_dir=shared)
    monkeypatch.setattr(
        recalibration,
        "reviewed_examples",
        lambda db, model: examples(model, 60, disagree=0.4, seed=2),
    )
    monkeypatch.setattr(repo, "mark_feedback_used", lambda db, ids: None)

    result = recalibrate_from_feedback(
        get_engine(), live, alpha=0.1, min_new_reviews=10, trained=trained_file
    )

    assert result is not None
    assert result.model.version == "tiny-2-recal60"
    assert (shared / "severity_log.tiny-1-recal40.json").exists()  # the old one is kept
    os.utime(live, ns=(time.time_ns(), time.time_ns() + 1_000_000))
    assert engine.refresh()
    assert engine.model is not None
    assert engine.model.version == "tiny-2-recal60"


@pytest.fixture
async def runner() -> AsyncIterator[TriageRunner]:
    init_db(get_engine())
    services = await Services.create()
    yield TriageRunner(services)
    await services.aclose()


async def test_reviews_recalibrate_the_model_and_running_engines_reload_it(
    runner: TriageRunner, tmp_path: Path
) -> None:
    services, engine = runner.services, runner.services.engine
    trained_file = services.config.severity.log_model_file
    trained = LinearModel.load(trained_file)
    path = tmp_path / "severity_log.json"
    shutil.copy(trained_file, path)  # never touch the committed model
    services.severity.model_path = path

    builder = ScenarioBuilder(LinePools.from_loghub(FIXTURES))
    modes = ["bgl.kernel_panic", "openssh.bruteforce", "hdfs.block_serve_exceptions"]
    for i in range(MIN_REVIEWED + 1):
        mode = modes[i % len(modes)]
        scenario = builder.build(mode, seed=100 + i, nodes=3, duration_min=5, incident_per_min=6)
        outcome = await runner.start(
            TriageRequest(system=mode.split(".")[0], logs=scenario.lines, synthetic=True)
        )
        assert outcome.status is RunStatus.AWAITING_REVIEW
        assert outcome.interrupt is not None
        if i == 0:
            decision = {"decision": "reject", "reviewer": "ana", "comment": "duplicate"}
        elif i % 3 == 0:
            other = "SEV2" if outcome.interrupt["severity"] != "SEV2" else "SEV3"
            decision = {"decision": "edit", "reviewer": "raj", "edits": {"severity": other}}
        else:
            decision = {"decision": "approve", "reviewer": "ana"}
        await runner.resume(outcome.run_id, decision)

    stored = repo.review_feedback(engine)
    assert len(stored) == MIN_REVIEWED + 1
    assert all(set(trained.feature_names) <= set(value["model_row"]) for _, value, _ in stored)
    reviewed = reviewed_examples(engine, trained)
    assert len(reviewed) == MIN_REVIEWED  # the rejection settles no severity

    assert recalibrate_from_feedback(engine, path, alpha=0.1, min_new_reviews=11) is None
    result = recalibrate_from_feedback(engine, path, alpha=0.1, min_new_reviews=MIN_REVIEWED)
    assert result is not None
    assert (result.reviewed, result.new_reviews) == (MIN_REVIEWED, MIN_REVIEWED)
    assert result.coverage_after >= 0.9
    saved = LinearModel.load(path)
    assert saved.version == f"{trained.version}-recal{MIN_REVIEWED}"
    assert (tmp_path / f"severity_log.{trained.version}.json").exists()  # the previous version
    used = {fid: flag for fid, _, flag in repo.review_feedback(engine)}
    assert all(used[e.feedback_id] for e in reviewed)

    assert services.severity.refresh()  # a running engine picks up the new file
    assert services.severity.model is not None
    assert services.severity.model.version == saved.version
    assert not services.severity.refresh()

    assert recalibrate_from_feedback(engine, path, alpha=0.1, min_new_reviews=1) is None
    shutil.copy(trained_file, path)  # a model restored from an older file ...
    again = recalibrate_from_feedback(engine, path, alpha=0.1, min_new_reviews=MIN_REVIEWED)
    assert again is not None  # ... recalibrates again from the shared database
    assert LinearModel.load(path).version == saved.version

    # In containers the live model sits on the shared volume; the image only has the trained one.
    shared = tmp_path / "shared"
    shared.mkdir()
    live = live_model_path(trained_file, shared)
    fresh = SeverityEngine.load(services.config.severity, models_dir=shared)
    assert fresh.model is not None
    assert (fresh.model.version, fresh.model_path) == (trained.version, live)
    first = recalibrate_from_feedback(
        engine, live, alpha=0.1, min_new_reviews=MIN_REVIEWED, trained=trained_file
    )
    assert first is not None
    assert LinearModel.load(live).version == saved.version
    assert LinearModel.load(trained_file).version == trained.version  # never written
    assert fresh.refresh()  # every container sharing the volume picks it up
    assert fresh.model.version == saved.version


# --- blind checks and adaptive conformal inference ---------------------------------------------


def calibrated_tiny(alpha: float) -> LinearModel:
    """The tiny model with a per-level calibration fitted on its own agreeing windows."""
    model = tiny_model(conformal_q=0.2)
    rng = np.random.default_rng(9)
    xs = rng.uniform(-2, 2, size=300)
    probs = model.predict_proba(model.matrix([{"x": float(x)} for x in xs]))
    tops = probs.argmax(axis=1)
    scores = {
        cls: sorted(float(1 - probs[i, k]) for i in range(len(xs)) if tops[i] == k)
        for k, cls in enumerate(CLASSES)
    }
    model.calibrations = {
        FAMILIAR: Calibration(
            temperature=1.0,
            alphas=dict.fromkeys(CLASSES, alpha),
            scores=scores,
            guard_classes=["SEV1", "SEV2"],
            ordered=True,
        )
    }
    return model


def checks(
    model: LinearModel, n: int, *, disagree: float, seed: int, start: int = 1
) -> list[BlindCheck]:
    rng = np.random.default_rng(seed)
    out: list[BlindCheck] = []
    for i in range(n):
        x = float(rng.uniform(-2, 2))
        top = int(np.argmax(model.predict_proba(model.matrix([{"x": x}]))[0]))
        label = top if rng.random() >= disagree else (top + 1 if top < 3 else 2)
        out.append(BlindCheck(start + i, {"x": x}, CLASSES[label], FAMILIAR))
    return out


def _missed(model: LinearModel, sample: list[BlindCheck]) -> float:
    calibration = model.calibrations[FAMILIAR]
    return float(
        np.mean(
            [
                c.label
                not in calibration.classes_in(
                    model.predict_proba(model.matrix([c.row]))[0], CLASSES
                )
                for c in sample
            ]
        )
    )


def test_over_any_stream_each_level_misses_close_to_its_target_share(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adaptive conformal inference's bound (Gibbs and Candès, 2021): over n checks of a level,
    the share its sets missed exceeds the target by at most (max(a, 1 - a) + step) / (step n),
    whatever the checks were. Here the labels are random, so the sets must widen a long way to
    keep it. (A level with no calibration scores is never ruled out, so it can only miss less; a
    batch recalibration starts the bound afresh, so this stream stays below one.)"""
    monkeypatch.setattr(recalibration, "BATCH_PER_LEVEL", 10**9)
    model = calibrated_tiny(alpha=0.1)
    rng = np.random.default_rng(4)
    stream = [
        BlindCheck(i + 1, {"x": float(rng.uniform(-2, 2))}, CLASSES[int(rng.integers(4))], FAMILIAR)
        for i in range(1_600)
    ]
    adapted, summary = adapt(model, stream, targets=dict.fromkeys(CLASSES, 0.1))
    assert summary["applied"] == 1_600
    for level in CLASSES:
        n = summary["by_level"][level]["checks"]
        share = summary["by_level"][level]["missed"] / n
        assert share - 0.1 <= (0.9 + ACI_STEP) / (ACI_STEP * n) + 1e-9
    assert adapted.version == "tiny-1-aci1600"
    assert adapted.metadata["aci"]["applied_through"] == 1_600
    assert model.calibrations[FAMILIAR].alphas == dict.fromkeys(CLASSES, 0.1)  # left as it was


def test_a_level_the_sets_keep_missing_gets_a_lower_miss_rate_until_they_hold_it() -> None:
    model = calibrated_tiny(alpha=0.1)
    calibration = model.calibrations[FAMILIAR]
    row = {"x": 2.0}  # the model is sure of SEV1 here
    assert "SEV4" not in calibration.classes_in(
        model.predict_proba(model.matrix([row]))[0], CLASSES
    )
    stream = [BlindCheck(i + 1, row, "SEV4", FAMILIAR) for i in range(60)]
    adapted, summary = adapt(model, stream, targets=dict.fromkeys(CLASSES, 0.1))
    assert adapted.calibrations[FAMILIAR].alphas["SEV4"] < 0.1
    held = adapted.calibrations[FAMILIAR].classes_in(
        adapted.predict_proba(adapted.matrix([row]))[0], CLASSES
    )
    assert "SEV4" in held
    assert summary["missed"] < 60  # it stopped missing once the set reached SEV4


def test_each_blind_check_moves_the_sets_once() -> None:
    model = calibrated_tiny(alpha=0.1)
    targets = dict.fromkeys(CLASSES, 0.1)
    stream = checks(model, 30, disagree=0.2, seed=6)
    adapted, _ = adapt(model, stream, targets=targets)
    again, summary = adapt(adapted, stream, targets=targets)
    assert summary["applied"] == 0
    assert again.calibrations[FAMILIAR].alphas == adapted.calibrations[FAMILIAR].alphas
    more, summary = adapt(
        adapted, [*stream, *checks(model, 5, disagree=0.2, seed=7, start=31)], targets=targets
    )
    assert summary["applied"] == 5
    assert more.metadata["aci"]["checks"] == 35


def test_a_level_with_enough_blind_checks_is_calibrated_on_them() -> None:
    model = calibrated_tiny(alpha=0.1)
    targets = dict.fromkeys(CLASSES, 0.1)
    many = [c for c in checks(model, 900, disagree=0.0, seed=8) if c.label == "SEV1"]
    assert len(many) >= BATCH_PER_LEVEL
    adapted, summary = adapt(model, many, targets=targets)
    assert summary["replaced_scores"] == {FAMILIAR: ["SEV1"]}
    assert len(adapted.calibrations[FAMILIAR].scores["SEV1"]) == len(many)
    assert adapted.calibrations[FAMILIAR].alphas["SEV1"] == 0.1  # back to target on fresh scores
    _, again = adapt(adapted, many, targets=targets)
    assert again["replaced_scores"] == {}  # no new batch since


def test_blind_checks_in_the_database_adapt_the_live_model(tmp_path: Path) -> None:
    engine = get_engine()
    init_db(engine)
    trained = tmp_path / "severity_log.json"
    calibrated_tiny(alpha=0.1).save(trained)
    live = tmp_path / "live" / "severity_log.json"
    for i, check in enumerate(checks(calibrated_tiny(0.1), 12, disagree=0.5, seed=10)):
        repo.save_feedback(
            engine,
            f"run-{i}",
            "blind_check",
            {"to": check.label, "model_row": check.row, "calibration": FAMILIAR},
            author="ana",
        )
    targets = dict.fromkeys(CLASSES, 0.1)
    result = adapt_from_blind_checks(engine, live, targets=targets, trained=trained)
    assert result is not None
    assert result["applied"] == 12
    assert LinearModel.load(live).metadata["aci"]["checks"] == 12
    assert adapt_from_blind_checks(engine, live, targets=targets, trained=trained) is None


def test_blind_checks_of_serious_incidents_feed_the_severe_miss_alarm_in_arrival_order(
    tmp_path: Path,
) -> None:
    engine = get_engine()
    init_db(engine)
    trained = tmp_path / "severity_log.json"
    calibrated_tiny(alpha=0.1).save(trained)
    live = tmp_path / "live" / "severity_log.json"
    # Five serious incidents, four of them rated SEV3 or SEV4 by ARIA; one the person rated SEV3
    # (not a serious incident, so not a check of the promise); one check without ARIA's level.
    rows = [
        ("SEV1", "SEV4"),
        ("SEV2", "SEV4"),
        ("SEV3", "SEV3"),
        ("SEV1", "SEV2"),
        ("SEV2", "SEV3"),
        ("SEV1", None),
        ("SEV1", "SEV4"),
    ]
    for i, (theirs, aria) in enumerate(rows):
        value = {"to": theirs, "model_row": {"x": -2.0}, "calibration": FAMILIAR}
        if aria is not None:
            value["aria"] = aria
        repo.save_feedback(engine, f"run-{i}", "blind_check", value, author="ana")
    targets = dict.fromkeys(CLASSES, 0.1)
    result = adapt_from_blind_checks(engine, live, targets=targets, trained=trained, dry_run=True)
    assert result is not None
    alarm = result["severe_miss_alarm"]
    assert (alarm["checks"], alarm["misses"]) == (5, 4)
    assert alarm["promised"] == 0.1  # no certified guard: the serious levels' target
    assert alarm["raised"]
    assert alarm["raised_at"] <= 5
    assert not live.exists()  # a dry run, and the alarm itself, change nothing
