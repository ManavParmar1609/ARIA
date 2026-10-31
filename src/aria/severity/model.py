"""Calibrated linear classifiers with conformal prediction sets.

* Fitting uses scikit-learn's multinomial logistic regression on standardised features.
* Calibration fits a single temperature on held-out data (Guo et al., 2017), which keeps the
  ranking and fixes over- or under-confidence.
* Split-conformal prediction (least ambiguous set-valued classifier, Sadinle et al., 2019) turns
  calibrated probabilities into a set that contains the true class with probability at least
  ``1 - alpha`` on exchangeable data. A set with one class is a confident call; a larger set is
  what the LLM adjudicator (or a human) chooses within.

Models are stored as JSON: coefficients, scaler statistics, temperature and conformal
threshold. Inference is plain numpy, and loading a model file cannot execute code.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize_scalar

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


def softmax(logits: FloatArray) -> FloatArray:
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return np.asarray(exp / exp.sum(axis=-1, keepdims=True), dtype=np.float64)


def nll(probs: FloatArray, y: IntArray) -> float:
    picked = probs[np.arange(len(y)), y]
    return float(-np.mean(np.log(np.clip(picked, 1e-12, 1.0))))


def fit_temperature(logits: FloatArray, y: IntArray) -> float:
    """Temperature that minimises negative log-likelihood on calibration data."""
    if len(y) == 0:
        return 1.0
    result = minimize_scalar(
        lambda log_t: nll(softmax(logits / math.exp(log_t)), y),
        bounds=(math.log(0.05), math.log(20.0)),
        method="bounded",
    )
    return float(math.exp(result.x))


def conformal_threshold(probs: FloatArray, y: IntArray, alpha: float) -> float:
    """LAC threshold: the finite-sample-corrected (1 - alpha) quantile of 1 - p(true class)."""
    n = len(y)
    if n == 0:
        return 1.0
    scores = 1.0 - probs[np.arange(n), y]
    level = min(1.0, math.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


def expected_calibration_error(probs: FloatArray, y: IntArray, bins: int = 10) -> float:
    confidence = probs.max(axis=1)
    correct = probs.argmax(axis=1) == y
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for lo, hi in itertools.pairwise(edges):
        mask = (confidence > lo) & (confidence <= hi)
        if mask.any():
            ece += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())
    return float(ece)


def live_model_path(trained: Path, models_dir: Path) -> Path:
    """Where recalibrated models are written: ``models_dir``, a volume all containers share.

    The trained model ships with the code at ``trained``; readers fall back to it until the first
    recalibration writes the live file. In a checkout both paths are ``models/``.
    """
    return models_dir / trained.name


@dataclass
class LinearModel:
    """Softmax over ``coef @ standardised(x) + intercept``, divided by a temperature."""

    name: str
    classes: list[str]
    feature_names: list[str]
    mean: FloatArray
    scale: FloatArray
    coef: FloatArray  # (n_classes, n_features)
    intercept: FloatArray  # (n_classes,)
    temperature: float = 1.0
    conformal_q: float | None = None
    alpha: float = 0.1
    version: str = "unversioned"
    metadata: dict[str, Any] = field(default_factory=dict)
    # The smallest and largest value of each feature in the training data. Past them the linear
    # model extrapolates; models saved before these were recorded have none.
    low: FloatArray | None = None
    high: FloatArray | None = None

    @property
    def trained_version(self) -> str:
        """The trained model this one comes from: itself, or the one it recalibrates."""
        return str(self.metadata.get("trained_version", self.version))

    # --- inference -----------------------------------------------------------------------------

    def matrix(self, rows: Sequence[dict[str, float]]) -> FloatArray:
        return np.array(
            [[row.get(name, 0.0) for name in self.feature_names] for row in rows], dtype=np.float64
        )

    def standardise(self, x: FloatArray) -> FloatArray:
        return (x - self.mean) / self.scale

    def outside_training(
        self, x_row: FloatArray, limit: float, tolerance: float | None = None
    ) -> list[str]:
        """Features of one row the model has not seen values like in training.

        A feature is outside when it lies more than ``limit`` standard deviations from the
        training mean, or, with ``tolerance`` and recorded ranges, beyond the training range by
        more than that share of the range. There the linear model extrapolates, and its
        probabilities mean nothing. A feature the model gave no weight cannot mislead it, so only
        weighted features count for the range.
        """
        outside = np.abs(self.standardise(x_row)) > limit
        if tolerance is not None and self.low is not None and self.high is not None:
            used = np.abs(self.coef).max(axis=0) > 1e-9
            margin = tolerance * np.maximum(self.high - self.low, 1e-9)
            beyond = (x_row > self.high + margin) | (x_row < self.low - margin)
            outside |= used & beyond
        return [self.feature_names[i] for i in np.flatnonzero(outside)]

    def logits(self, x: FloatArray) -> FloatArray:
        return np.asarray(self.standardise(x) @ self.coef.T + self.intercept, dtype=np.float64)

    def predict_proba(self, x: FloatArray) -> FloatArray:
        return softmax(self.logits(x) / self.temperature)

    def prediction_sets(self, probs: FloatArray) -> list[list[str]]:
        """Classes whose probability clears the conformal threshold; never empty."""
        if self.conformal_q is None:
            return [[self.classes[int(np.argmax(row))]] for row in probs]
        cutoff = 1.0 - self.conformal_q
        sets: list[list[str]] = []
        for row in probs:
            chosen = [self.classes[i] for i in range(len(self.classes)) if row[i] >= cutoff]
            sets.append(chosen or [self.classes[int(np.argmax(row))]])
        return sets

    def contributions(self, x_row: FloatArray, cls: str, top: int = 5) -> list[tuple[str, float]]:
        """Per-feature contribution to a class's logit, relative to the average class."""
        z = self.standardise(x_row)
        idx = self.classes.index(cls)
        relative = self.coef[idx] - self.coef.mean(axis=0)
        parts = relative * z
        order = np.argsort(-np.abs(parts))[:top]
        return [(self.feature_names[i], round(float(parts[i]), 3)) for i in order if parts[i] != 0]

    # --- persistence ---------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        ranges = (
            {"low": self.low.tolist(), "high": self.high.tolist()}
            if self.low is not None and self.high is not None
            else {}
        )
        return {
            **ranges,
            "format": "aria.linear_model.v1",
            "name": self.name,
            "version": self.version,
            "classes": self.classes,
            "feature_names": self.feature_names,
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "coef": self.coef.tolist(),
            "intercept": self.intercept.tolist(),
            "temperature": self.temperature,
            "conformal_q": self.conformal_q,
            "alpha": self.alpha,
            "metadata": self.metadata,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1, sort_keys=True), encoding="utf-8")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LinearModel:
        if raw.get("format") != "aria.linear_model.v1":
            msg = f"unsupported model format {raw.get('format')!r}"
            raise ValueError(msg)
        model = cls(
            name=raw["name"],
            classes=list(raw["classes"]),
            feature_names=list(raw["feature_names"]),
            mean=np.array(raw["mean"], dtype=np.float64),
            scale=np.array(raw["scale"], dtype=np.float64),
            coef=np.array(raw["coef"], dtype=np.float64),
            intercept=np.array(raw["intercept"], dtype=np.float64),
            temperature=float(raw["temperature"]),
            conformal_q=None if raw.get("conformal_q") is None else float(raw["conformal_q"]),
            alpha=float(raw["alpha"]),
            version=str(raw["version"]),
            metadata=dict(raw.get("metadata") or {}),
            low=None if raw.get("low") is None else np.array(raw["low"], dtype=np.float64),
            high=None if raw.get("high") is None else np.array(raw["high"], dtype=np.float64),
        )
        k, f = len(model.classes), len(model.feature_names)
        if model.coef.shape != (k, f) or model.intercept.shape != (k,) or model.mean.shape != (f,):
            msg = "model arrays do not match its classes and features"
            raise ValueError(msg)
        for bound in (model.low, model.high):
            if bound is not None and bound.shape != (f,):
                msg = "model ranges do not match its features"
                raise ValueError(msg)
        return model

    @classmethod
    def load(cls, path: Path) -> LinearModel:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def fit_linear_model(
    name: str,
    x: FloatArray,
    y: Sequence[str],
    *,
    classes: Sequence[str],
    feature_names: Sequence[str],
    c: float = 1.0,
    class_weight: str | None = "balanced",
    seed: int = 0,
) -> LinearModel:
    """Fit multinomial logistic regression; temperature and conformal threshold come later."""
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415 - training only

    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-9] = 1.0
    z = (x - mean) / scale
    present = [cls for cls in classes if cls in set(y)]
    clf = LogisticRegression(C=c, class_weight=class_weight, max_iter=5_000, random_state=seed)
    clf.fit(z, list(y))
    coef = np.zeros((len(classes), x.shape[1]))
    intercept = np.full(len(classes), -30.0)  # classes never seen in training get ~zero mass
    learned = [str(c_) for c_ in clf.classes_]
    if len(learned) == 2:  # binary: sklearn keeps one row for the positive class
        positive = classes.index(learned[1])
        negative = classes.index(learned[0])
        coef[positive], intercept[positive] = clf.coef_[0], clf.intercept_[0]
        coef[negative], intercept[negative] = 0.0, 0.0
    else:
        for row, cls in enumerate(learned):
            coef[classes.index(cls)] = clf.coef_[row]
            intercept[classes.index(cls)] = clf.intercept_[row]
    return LinearModel(
        name=name,
        classes=list(classes),
        feature_names=list(feature_names),
        mean=mean,
        scale=scale,
        coef=coef,
        intercept=intercept,
        metadata={"c": c, "class_weight": class_weight, "trained_classes": present},
        low=x.min(axis=0),
        high=x.max(axis=0),
    )


def calibrate(
    model: LinearModel,
    x_temp: FloatArray,
    y_temp: Sequence[str],
    x_conf: FloatArray,
    y_conf: Sequence[str],
    *,
    alpha: float,
) -> LinearModel:
    """Fit the temperature on one held-out split and the conformal threshold on another."""
    to_idx = {cls: i for i, cls in enumerate(model.classes)}
    yt = np.array([to_idx[v] for v in y_temp], dtype=np.int64)
    yc = np.array([to_idx[v] for v in y_conf], dtype=np.int64)
    model.temperature = fit_temperature(model.logits(x_temp), yt) if len(yt) else 1.0
    model.alpha = alpha
    model.conformal_q = (
        conformal_threshold(model.predict_proba(x_conf), yc, alpha) if len(yc) else None
    )
    model.metadata.update(
        {
            "n_temperature": len(yt),
            "n_conformal": len(yc),
            "calibrated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    return model
