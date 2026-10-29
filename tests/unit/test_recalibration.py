"""Recalibrating the severity model on reviewed incidents: the active-learning loop."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest

from aria.contracts.inputs import TriageRequest
from aria.contracts.run import RunStatus
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db
from aria.graph.runner import TriageRunner
from aria.services import Services
from aria.severity.engine import SeverityEngine
from aria.severity.model import LinearModel, live_model_path
from aria.severity.recalibration import (
    MIN_REVIEWED,
    ReviewedExample,
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
