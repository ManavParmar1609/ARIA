"""Training data and fitting for the log-severity model.

Labelled windows come from the semi-synthetic scenario suite (real Loghub lines, synthetic
composition; BGL scenarios labelled by the alert-tag rubric, others by the documented scenario
policy). Each split uses different scenario seeds, so no window appears in two splits:

* train: fit the logistic regression (C chosen by cross-validation on train only);
* temperature: fit the calibration temperature;
* conformal: fit the conformal threshold;
* test: reserved for ``make eval``.

Every window is parsed by the production parser with the production rules, so training sees
exactly the features the running system computes.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import numpy as np

from aria.config import GuardrailConfig
from aria.contracts.base import SEVERITY_ORDER, Severity
from aria.contracts.parsing import ParsedBatch, WindowFeatures
from aria.data.scenarios import LinePools, Scenario, ScenarioBuilder
from aria.evidence import EvidenceStore
from aria.parsing.parser import parse_lines
from aria.severity.features import log_feature_names, log_feature_row
from aria.severity.model import (
    LinearModel,
    calibrate,
    conformal_threshold,
    expected_calibration_error,
    fit_linear_model,
    nll,
)
from aria.severity.rules import RuleEvaluation, RuleSet, feature_space

TRAIN_SALT = b"aria-training-v1"  # fixed so training features are reproducible
CLASSES = [str(s) for s in SEVERITY_ORDER]


@dataclass(frozen=True)
class SplitSeeds:
    train: tuple[int, ...] = (11, 12, 13, 14)
    temperature: tuple[int, ...] = (21,)
    conformal: tuple[int, ...] = (31, 32)
    test: tuple[int, ...] = (41, 42)


@dataclass
class LabelledWindow:
    id: str
    system: str
    failure_mode: str
    severity: Severity
    values: dict[str, float]
    rules: RuleEvaluation
    synthetic: bool
    label_source: str
    benign: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def row(self) -> dict[str, float]:
        return log_feature_row(self.values, self.rules)


@cache
def _known_templates(builder: ScenarioBuilder, system: str) -> tuple[str, ...]:
    """Templates of routine traffic, standing in for the history a deployment accumulates."""
    history = builder.build_quiet(system, seed=9_999, duration_min=30)
    return tuple(t.template for t in _parse(system, history.lines, ()).templates)


def _parse(system: str, lines: Sequence[str], known: Sequence[str]) -> ParsedBatch:
    return parse_lines(
        lines,
        system=system,
        guard=GuardrailConfig(),
        evidence=EvidenceStore(),
        known_templates=known,
        salt=TRAIN_SALT,
    ).batch


def _features(system: str, lines: Sequence[str], known: Sequence[str]) -> WindowFeatures:
    return _parse(system, lines, known).features


def featurize_all(
    scenarios: Sequence[Scenario], builder: ScenarioBuilder, rules: RuleSet, *, workers: int = 1
) -> list[LabelledWindow]:
    """Parse every scenario with the production parser (in parallel processes if asked)."""
    known = {s.system: _known_templates(builder, s.system) for s in scenarios}
    args = (
        [s.system for s in scenarios],
        [s.lines for s in scenarios],
        [known[s.system] for s in scenarios],
    )
    if workers > 1 and len(scenarios) > 2 * workers:
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
            features = list(pool.map(_features, *args, chunksize=4))
    else:
        features = [_features(*item) for item in zip(*args, strict=True)]
    windows: list[LabelledWindow] = []
    for scenario, feats in zip(scenarios, features, strict=True):
        values = feature_space(feats)
        mode = builder.pools.modes.get(f"{scenario.system}.{scenario.failure_mode}")
        windows.append(
            LabelledWindow(
                id=scenario.id,
                system=scenario.system,
                failure_mode=scenario.failure_mode,
                severity=scenario.severity,
                values=values,
                rules=rules.evaluate(values),
                synthetic=scenario.synthetic,
                label_source=scenario.label_source,
                benign=bool(mode and mode.benign),
                meta={"nodes": len(scenario.nodes), "incident_lines": scenario.incident_lines},
            )
        )
    return windows


def featurize(scenario: Scenario, builder: ScenarioBuilder, rules: RuleSet) -> LabelledWindow:
    return featurize_all([scenario], builder, rules)[0]


def build_split(
    builder: ScenarioBuilder,
    rules: RuleSet,
    seeds: Iterable[int],
    *,
    per_mode: int,
    quiet_per_system: int,
    workers: int = 1,
) -> list[LabelledWindow]:
    scenarios = [
        scenario
        for seed in seeds
        for scenario in builder.suite(
            seed=seed, per_mode=per_mode, quiet_per_system=quiet_per_system
        )
    ]
    return featurize_all(scenarios, builder, rules, workers=workers)


def _xy(
    model_features: Sequence[str], windows: Sequence[LabelledWindow]
) -> tuple[np.ndarray, list[str]]:
    rows = [w.row() for w in windows]
    x = np.array(
        [[row.get(name, 0.0) for name in model_features] for row in rows], dtype=np.float64
    )
    return x, [str(w.severity) for w in windows]


def _choose_c(x: np.ndarray, y: list[str], grid: Sequence[float], seed: int) -> float:
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415 - training only
    from sklearn.model_selection import StratifiedKFold, cross_val_score  # noqa: PLC0415
    from sklearn.pipeline import make_pipeline  # noqa: PLC0415
    from sklearn.preprocessing import StandardScaler  # noqa: PLC0415

    counts = Counter(y)
    folds = max(2, min(4, *counts.values()))
    best, best_score = grid[0], -np.inf
    for c in grid:
        pipe = make_pipeline(
            StandardScaler(),
            LogisticRegression(C=c, class_weight="balanced", max_iter=5_000, random_state=seed),
        )
        cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
        score = float(np.mean(cross_val_score(pipe, x, y, cv=cv, scoring="neg_log_loss")))
        if score > best_score:
            best, best_score = c, score
    return best


def fit_log_model(
    train: Sequence[LabelledWindow],
    temperature: Sequence[LabelledWindow],
    conformal: Sequence[LabelledWindow],
    *,
    alpha: float,
    rules_version: str,
    seed: int = 0,
    c_grid: Sequence[float] = (0.03, 0.1, 0.3, 1.0, 3.0),
) -> tuple[LinearModel, dict[str, Any]]:
    names = log_feature_names()
    x_train, y_train = _xy(names, train)
    x_temp, y_temp = _xy(names, temperature)
    x_conf, y_conf = _xy(names, conformal)
    c = _choose_c(x_train, y_train, c_grid, seed) if len(set(y_train)) > 1 else 1.0
    model = fit_linear_model(
        "severity_log", x_train, y_train, classes=CLASSES, feature_names=names, c=c, seed=seed
    )
    calibrate(model, x_temp, y_temp, x_conf, y_conf, alpha=alpha)
    digest = hashlib.sha256(model.coef.round(6).tobytes()).hexdigest()[:8]
    model.version = f"severity-log-{datetime.now(UTC):%Y%m%d}-{digest}"

    def summary(x: np.ndarray, y: list[str]) -> dict[str, Any]:
        if not y:
            return {}
        idx = np.array([CLASSES.index(v) for v in y])
        probs = model.predict_proba(x)
        sets = model.prediction_sets(probs)
        return {
            "n": len(y),
            "accuracy": round(float((probs.argmax(axis=1) == idx).mean()), 4),
            "nll": round(nll(probs, idx), 4),
            "ece": round(expected_calibration_error(probs, idx), 4),
            "coverage": round(float(np.mean([v in s for v, s in zip(y, sets, strict=True)])), 4),
            "mean_set_size": round(float(np.mean([len(s) for s in sets])), 3),
        }

    report = {
        "model_version": model.version,
        "rules_version": rules_version,
        "c": c,
        "alpha": alpha,
        "temperature": round(model.temperature, 4),
        "conformal_q": model.conformal_q,
        "labels": {
            "train": dict(Counter(y_train)),
            "temperature": dict(Counter(y_temp)),
            "conformal": dict(Counter(y_conf)),
        },
        "train": summary(x_train, y_train),
        "temperature_split": summary(x_temp, y_temp),
        "conformal_split": summary(x_conf, y_conf),
        "synthetic": all(w.synthetic for w in [*train, *temperature, *conformal]),
    }
    model.metadata.update(
        {
            "rules_version": rules_version,
            "training_data": "semi-synthetic scenario suite (real Loghub lines); see docs/data-card.md",
            "label_sources": sorted({w.label_source for w in train}),
            "n_train": len(train),
            "synthetic": report["synthetic"],
        }
    )
    return model, report


def train_from_loghub(
    loghub_dir: Path,
    rules: RuleSet,
    *,
    alpha: float,
    seeds: SplitSeeds | None = None,
    per_mode: int = 6,
    quiet_per_system: int = 3,
    workers: int = 1,
) -> tuple[LinearModel, dict[str, Any]]:
    seeds = seeds or SplitSeeds()
    builder = ScenarioBuilder(LinePools.from_loghub(loghub_dir))
    sizes = {"per_mode": per_mode, "quiet_per_system": quiet_per_system, "workers": workers}
    train = build_split(builder, rules, seeds.train, **sizes)
    temp = build_split(builder, rules, seeds.temperature, **sizes)
    conf = build_split(builder, rules, seeds.conformal, **sizes)
    model, report = fit_log_model(train, temp, conf, alpha=alpha, rules_version=rules.version)
    report["seeds"] = {
        "train": seeds.train,
        "temperature": seeds.temperature,
        "conformal": seeds.conformal,
        "test (held out)": seeds.test,
    }
    report["suite"] = {"per_mode": per_mode, "quiet_per_system": quiet_per_system}
    model.metadata["seeds"] = report["seeds"]
    return model, report


def conformal_coverage(model: LinearModel, windows: Sequence[LabelledWindow]) -> float:
    """Share of windows whose true severity is inside the prediction set."""
    x, y = _xy(model.feature_names, windows)
    sets = model.prediction_sets(model.predict_proba(x))
    return float(np.mean([v in s for v, s in zip(y, sets, strict=True)])) if y else 0.0


__all__ = [
    "CLASSES",
    "LabelledWindow",
    "SplitSeeds",
    "build_split",
    "conformal_coverage",
    "conformal_threshold",
    "featurize",
    "fit_log_model",
    "train_from_loghub",
]
