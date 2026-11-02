"""Recalibrate the severity model on reviewed incidents: the active-learning loop.

Split-conformal prediction sets hold the true class ``1 - alpha`` of the time only on data like
the set they were calibrated on. ARIA's model was calibrated on semi-synthetic windows, and a
deployment's own incidents differ. So every human review records the run's model input and the
severity the reviewer settled on (an approval confirms ARIA's severity, an edit corrects it; a
rejection settles nothing and is left out). Once ``recalibrate_after`` reviews have gathered since
the loaded model was calibrated, ARIA recomputes the conformal threshold on all reviewed
incidents, saves the model under a new version (keeping the previous file beside it) and marks
those reviews used.

Only the threshold moves: coefficients and temperature stay as trained, so recalibration can
widen or narrow the prediction sets (and with them how often ARIA asks for review) but cannot
change which class the model ranks first. The guarantee is only as good as the reviews: approvals
count as confirmations.

Models with per-level calibrations learn from blind checks instead (:func:`adapt`). A blind check
is a person rating an incident before seeing ARIA's level, so it is free of the pull an approval
button has toward agreeing. After each check, in the order they arrived, the checked level's miss
rate moves toward its target: down (a wider set) when the set missed the person's level, up a
little when it held it. That is adaptive conformal inference (Gibbs and Candès, NeurIPS 2021):
over any sequence of checks, the share the sets miss stays within a known distance of the target,
however the deployment's incidents differ from the training data. Once a level has
``BATCH_PER_LEVEL`` checks, its calibration scores are replaced by the checks' own.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import Engine

from aria.db import record
from aria.db import repository as repo
from aria.observability.logging import get_logger
from aria.severity.conformal import FAMILIAR
from aria.severity.model import LinearModel, conformal_threshold

log = get_logger(__name__)

# Below this many reviews the conformal quantile cannot be finite for alpha = 0.1, (n + 1)(1 - a)
# must stay below n; the configured minimum is higher still.
MIN_REVIEWED = 10


# The adaptive step: larger follows a changing deployment faster, smaller wobbles less.
ACI_STEP = 0.05
# The adaptive miss rate may dip below zero: its set then holds every level until enough checks
# are covered again. Clipping it at zero would forget misses and break the long-run bound; the
# ceiling only ever errs toward wider sets.
ALPHA_FLOOR, ALPHA_CEILING = -ACI_STEP, 1.0
# Blind checks of one level needed before they replace that level's calibration scores.
BATCH_PER_LEVEL = 100


@dataclass(frozen=True)
class BlindCheck:
    """A person's own rating of an incident, given before they saw ARIA's level."""

    feedback_id: int
    row: dict[str, float]
    label: str
    kind: str  # the calibration the incident's set came from


def blind_checks(engine: Engine, model: LinearModel) -> list[BlindCheck]:
    """Blind checks whose stored model input fits ``model``, oldest first."""
    needed = set(model.feature_names)
    checks: list[BlindCheck] = []
    for feedback_id, value, _used in repo.feedback_of(engine, "blind_check"):
        row, label = value.get("model_row"), value.get("to")
        if not isinstance(row, dict) or label not in model.classes or not needed <= set(row):
            continue
        kind = str(value.get("calibration") or FAMILIAR)
        checks.append(
            BlindCheck(feedback_id, {str(k): float(v) for k, v in row.items()}, label, kind)
        )
    return checks


def adapt(
    model: LinearModel,
    checks: Sequence[BlindCheck],
    *,
    targets: Mapping[str, float],
    step: float = ACI_STEP,
) -> tuple[LinearModel, dict[str, Any]]:
    """A copy of ``model`` whose calibrations have followed the blind checks it has not seen yet.

    Checks up to the model's ``aci.applied_through`` were applied before and are skipped; the
    rest move the miss rate of their level, in order. Returns the copy and what changed.
    """
    adapted = copy.deepcopy(model)
    state = dict(adapted.metadata.get("aci") or {})
    after = int(state.get("applied_through", 0))
    applied = misses = 0
    by_level: dict[str, dict[str, int]] = {c: {"checks": 0, "missed": 0} for c in adapted.classes}
    for check in checks:
        if check.feedback_id <= after:
            continue
        kind = check.kind if check.kind in adapted.calibrations else FAMILIAR
        calibration = adapted.calibrations.get(kind)
        if calibration is None:
            continue
        probs = adapted.predict_proba(adapted.matrix([check.row]), kind)[0]
        missed = check.label not in calibration.classes_in(probs, adapted.classes)
        target = float(targets.get(check.label, calibration.alphas[check.label]))
        moved = calibration.alphas[check.label] + step * (target - (1.0 if missed else 0.0))
        calibration.alphas[check.label] = min(ALPHA_CEILING, max(ALPHA_FLOOR, moved))
        applied += 1
        misses += missed
        by_level[check.label]["checks"] += 1
        by_level[check.label]["missed"] += missed
        after = check.feedback_id
    # Each further BATCH_PER_LEVEL checks of a level replace its calibration scores with all of
    # that level's checks; between replacements, the adaptive miss rate carries on.
    replaced: dict[str, list[str]] = {}
    counts: dict[str, dict[str, int]] = {
        k: dict(v) for k, v in (state.get("replaced_at") or {}).items()
    }
    for kind, calibration in adapted.calibrations.items():
        for level in adapted.classes:
            own = [
                c
                for c in checks
                if c.label == level
                and (c.kind if c.kind in adapted.calibrations else FAMILIAR) == kind
            ]
            if len(own) - counts.get(kind, {}).get(level, 0) < BATCH_PER_LEVEL:
                continue
            probs = adapted.predict_proba(adapted.matrix([c.row for c in own]), kind)
            index = adapted.classes.index(level)
            calibration.scores[level] = sorted(float(1.0 - p[index]) for p in probs)
            calibration.alphas[level] = float(targets.get(level, calibration.alphas[level]))
            counts.setdefault(kind, {})[level] = len(own)
            replaced.setdefault(kind, []).append(level)
    total = int(state.get("checks", 0)) + applied
    summary = {
        "applied": applied,
        "missed": misses,
        "by_level": by_level,
        "checks": total,
        "replaced_scores": replaced,
        "alphas": {k: dict(c.alphas) for k, c in adapted.calibrations.items()},
    }
    if applied or replaced:
        base = adapted.trained_version
        adapted.version = f"{base}-aci{total}"
        adapted.metadata = {
            **adapted.metadata,
            "trained_version": base,
            "aci": {
                "applied_through": after,
                "checks": total,
                "replaced_at": counts,
                "step": step,
                "targets": dict(targets),
                "adapted_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        }
    return adapted, summary


def adapt_from_blind_checks(
    engine: Engine,
    model_path: Path,
    *,
    targets: Mapping[str, float],
    trained: Path | None = None,
    dry_run: bool = False,
    actor: str = "system",
) -> dict[str, Any] | None:
    """Apply new blind checks to the live model and save it; None when there is nothing new.

    Like :func:`recalibrate_from_feedback`, the live file starts from the shipped model until it
    exists, and starts again when an upgrade shipped a different one. A saved model goes on the
    decision record under ``actor`` (the job, or ``cli`` for the operator).
    """
    live = LinearModel.load(model_path) if model_path.exists() else None
    shipped = (
        LinearModel.load(trained)
        if trained is not None and trained != model_path and trained.exists()
        else None
    )
    model = live or shipped
    if live is not None and shipped is not None and live.trained_version != shipped.trained_version:
        model = shipped
    if model is None or not model.calibrations:
        return None
    adapted, summary = adapt(model, blind_checks(engine, model), targets=targets)
    if not summary["applied"] and not summary["replaced_scores"]:
        return None
    if not dry_run:
        save_model(adapted, model_path, previous=live or model)
        log.info(
            "severity.adapted",
            version=adapted.version,
            applied=summary["applied"],
            missed=summary["missed"],
        )
        record.append(
            engine,
            kind="recalibration",
            actor=actor,
            payload={
                "method": "blind_checks",
                "from_version": model.version,
                "model_version": adapted.version,
                "applied": summary["applied"],
                "missed": summary["missed"],
                "replaced_scores": summary["replaced_scores"],
                "file": model_path.name,
            },
        )
    return {"model_version": adapted.version, **summary}


@dataclass(frozen=True)
class ReviewedExample:
    feedback_id: int
    row: dict[str, float]
    label: str
    used: bool


@dataclass(frozen=True)
class Recalibration:
    model: LinearModel
    reviewed: int
    new_reviews: int
    coverage_before: float
    coverage_after: float
    threshold_before: float | None
    threshold_after: float
    mean_set_before: float
    mean_set_after: float


def reviewed_examples(engine: Engine, model: LinearModel) -> list[ReviewedExample]:
    """Human approvals and edits whose stored model input fits ``model``, oldest first."""
    needed = set(model.feature_names)
    examples: list[ReviewedExample] = []
    for feedback_id, value, used in repo.review_feedback(engine):
        row, label = value.get("model_row"), value.get("to")
        if value.get("decision") not in ("approve", "edit") or not isinstance(row, dict):
            continue
        if label not in model.classes or not needed <= set(row):
            continue
        examples.append(
            ReviewedExample(feedback_id, {str(k): float(v) for k, v in row.items()}, label, used)
        )
    return examples


def reviews_in(model: LinearModel) -> int:
    """How many reviews the loaded model was recalibrated on (0 for a model as trained)."""
    return (
        int(model.metadata.get("n_reviewed", 0)) if model.metadata.get("recalibrated_from") else 0
    )


def _coverage(model: LinearModel, probs: np.ndarray, labels: Sequence[str]) -> tuple[float, float]:
    sets = model.prediction_sets(probs)
    covered = [label in chosen for label, chosen in zip(labels, sets, strict=True)]
    return float(np.mean(covered)), float(np.mean([len(s) for s in sets]))


def recalibrate(
    model: LinearModel,
    examples: Sequence[ReviewedExample],
    *,
    alpha: float,
    new_reviews: int | None = None,
) -> Recalibration:
    """A copy of ``model`` whose conformal threshold is fitted on the reviewed examples."""
    labels = [e.label for e in examples]
    probs = model.predict_proba(model.matrix([e.row for e in examples]))
    before, set_before = _coverage(model, probs, labels)
    to_idx = {cls: i for i, cls in enumerate(model.classes)}
    threshold = conformal_threshold(probs, np.array([to_idx[v] for v in labels]), alpha)
    base = model.trained_version
    recalibrated = replace(
        model,
        conformal_q=threshold,
        alpha=alpha,
        version=f"{base}-recal{len(examples)}",
        metadata={
            **model.metadata,
            "trained_version": base,
            "recalibrated_from": model.version,
            "recalibrated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "n_reviewed": len(examples),
        },
    )
    after, set_after = _coverage(recalibrated, probs, labels)
    recalibrated.metadata.update(
        {"coverage_before": round(before, 4), "coverage_after": round(after, 4)}
    )
    return Recalibration(
        model=recalibrated,
        reviewed=len(examples),
        new_reviews=len(examples) if new_reviews is None else new_reviews,
        coverage_before=before,
        coverage_after=after,
        threshold_before=model.conformal_q,
        threshold_after=threshold,
        mean_set_before=set_before,
        mean_set_after=set_after,
    )


def save_model(model: LinearModel, path: Path, *, previous: LinearModel | None) -> None:
    """Write ``model`` to ``path`` atomically, keeping the previous version's file beside it."""
    if previous is not None:
        kept = path.with_name(f"{path.stem}.{previous.version}{path.suffix}")
        if not kept.exists():
            previous.save(kept)
    staging = path.with_name(f".{path.name}.tmp")
    model.save(staging)
    staging.replace(path)


def recalibrate_from_feedback(
    engine: Engine,
    model_path: Path,
    *,
    alpha: float,
    min_new_reviews: int,
    dry_run: bool = False,
    trained: Path | None = None,
    actor: str = "system",
) -> Recalibration | None:
    """Recalibrate when enough reviews have gathered since the loaded model was calibrated.

    ``model_path`` is the live model, read and rewritten in place; until it exists, or when it
    recalibrates a different trained model (one an upgrade replaced), the ``trained`` model is
    the starting point (and is never written). New reviews are counted against the model file's
    own record, not the ``used`` marks, so a model restored from an older file recalibrates again
    from the shared database. Returns None when there is nothing to do. A saved model goes on
    the decision record under ``actor``."""
    live = LinearModel.load(model_path) if model_path.exists() else None
    shipped = (
        LinearModel.load(trained)
        if trained is not None and trained != model_path and trained.exists()
        else None
    )
    model = live or shipped
    if live is not None and shipped is not None and live.trained_version != shipped.trained_version:
        # The engine ignores the previous release's recalibration, so start again from the
        # model this release ships; the old file is kept beside the new one.
        log.info("severity.recalibration_restarted", live=live.version, trained=shipped.version)
        model = shipped
    if model is None:
        return None
    examples = reviewed_examples(engine, model)
    new = len(examples) - reviews_in(model)
    if new < max(1, min_new_reviews) or len(examples) < MIN_REVIEWED:
        return None
    result = recalibrate(model, examples, alpha=alpha, new_reviews=new)
    if dry_run:
        return result
    save_model(result.model, model_path, previous=live or model)
    repo.mark_feedback_used(engine, [e.feedback_id for e in examples if not e.used])
    log.info(
        "severity.recalibrated",
        version=result.model.version,
        reviewed=result.reviewed,
        coverage_before=round(result.coverage_before, 3),
        coverage_after=round(result.coverage_after, 3),
        threshold_before=result.threshold_before,
        threshold_after=round(result.threshold_after, 4),
    )
    record.append(
        engine,
        kind="recalibration",
        actor=actor,
        payload={
            "method": "reviews",
            "from_version": model.version,
            "model_version": result.model.version,
            "reviewed": result.reviewed,
            "new_reviews": result.new_reviews,
            "coverage_before": round(result.coverage_before, 4),
            "coverage_after": round(result.coverage_after, 4),
            "threshold_before": result.threshold_before,
            "threshold_after": round(result.threshold_after, 4),
            "file": model_path.name,
        },
    )
    return result
