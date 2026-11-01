"""Fitting the severity model's calibrations: per-level promises that hold on new systems too.

Three ideas, each keeping a finite-sample guarantee on data like the calibration windows:

* **A promise per level** (class-conditional, or Mondrian, split conformal; Vovk et al., 2005;
  Ding et al., 2023). Each severity level gets its own threshold from calibration windows whose
  truth is that level, so a true SEV1 stays in the set at least ``1 - alpha_SEV1`` of the time
  even though SEV1 windows are rare. Serious levels get a tighter miss rate than the others.
* **Ordered sets.** Severity is ordinal: a set holding SEV1 and SEV3 also holds SEV2. Filling the
  gap only adds levels, so every promise still holds.
* **A guard on severe misses** (conformal risk control; Angelopoulos, Bates, Fisch, Lei and
  Schuster, ICLR 2024). The loss of a truly serious window is 1 when its set holds no serious
  level. A guard adds the likelier serious level when the serious levels' total probability is at
  least ``guard``; lowering the guard can only lower the loss, and the loosest guard whose
  corrected risk ``(sum of losses + 1) / (n + 1)`` stays at most ``epsilon`` bounds the expected
  severe-miss rate of the set by ``epsilon``.

What did not work, measured on validation seeds only: a second calibration for systems the model
never trained on, fitted on windows scored by models trained without each window's system (the
two-layer view of Dunn, Wasserman and Ramdas, 2022). Systems differ so much that its sets held
three or four levels on average, so ARIA rated nearly everything SEV1; fitting only the guard
that way missed its own target. ARIA instead marks such windows for a person to confirm (see
``SeverityEngine.trained_on``) and publishes how it does on unseen systems.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

from aria.severity.model import Calibration, FloatArray, fit_temperature, softmax

SERIOUS = ("SEV1", "SEV2")
FAMILIAR = "familiar"


def level_alphas(
    classes: Sequence[str], alpha: float, serious_alpha: float | None
) -> dict[str, float]:
    """The miss rate each level allows: ``serious_alpha`` for SEV1 and SEV2, ``alpha`` otherwise."""
    tight = alpha if serious_alpha is None else serious_alpha
    return {cls: (tight if cls in SERIOUS else alpha) for cls in classes}


def choose_guard(
    probs: FloatArray,
    truth: Sequence[str],
    classes: Sequence[str],
    calibration: Calibration,
    epsilon: float,
) -> tuple[float | None, float | None]:
    """``(guard, epsilon)``: the loosest guard that certifies a severe-miss risk of ``epsilon``.

    Returns ``(None, epsilon)`` when the sets already meet the target without a guard, and
    ``(None, None)`` when there are too few serious calibration windows to certify ``epsilon``
    at all (at least ``1 / epsilon - 1`` are needed).
    """
    serious = [i for i, t in enumerate(truth) if t in SERIOUS]
    n = len(serious)
    if n == 0 or 1.0 / (n + 1) > epsilon:
        return None, None
    idx = [classes.index(c) for c in SERIOUS if c in classes]
    unguarded = Calibration(
        temperature=calibration.temperature,
        alphas=calibration.alphas,
        scores=calibration.scores,
        ordered=calibration.ordered,
    )
    missed = sorted(
        (
            float(sum(probs[i, j] for j in idx))
            for i in serious
            if not set(unguarded.classes_in(probs[i], classes)) & set(SERIOUS)
        ),
        reverse=True,
    )
    # With the guard at the k-th largest missed probability, at least k misses are caught.
    need = math.ceil(len(missed) + 1 - epsilon * (n + 1) - 1e-9)
    if need <= 0:
        return None, epsilon
    return missed[need - 1], epsilon


def fit_calibration(
    logits_temperature: FloatArray,
    truth_temperature: Sequence[str],
    logits_conformal: FloatArray,
    truth_conformal: Sequence[str],
    classes: Sequence[str],
    *,
    alphas: Mapping[str, float],
    epsilon: float | None,
    source: str,
) -> Calibration:
    """Temperature on one split, then per-level thresholds and the guard on another."""
    to_idx = {cls: i for i, cls in enumerate(classes)}
    yt = np.array([to_idx[v] for v in truth_temperature], dtype=np.int64)
    temperature = fit_temperature(logits_temperature, yt) if len(yt) else 1.0
    probs = softmax(logits_conformal / temperature) if len(truth_conformal) else np.zeros((0, 0))
    scores = {
        cls: sorted(float(1.0 - probs[i, k]) for i, t in enumerate(truth_conformal) if t == cls)
        for k, cls in enumerate(classes)
    }
    calibration = Calibration(
        temperature=temperature,
        alphas=dict(alphas),
        scores=scores,
        guard_classes=[c for c in SERIOUS if c in classes],
        ordered=True,
        source=source,
    )
    if epsilon is not None and len(truth_conformal):
        calibration.guard, calibration.epsilon = choose_guard(
            probs, truth_conformal, classes, calibration, epsilon
        )
    return calibration


def coverage(
    calibration: Calibration, probs: FloatArray, truth: Sequence[str], classes: Sequence[str]
) -> dict[str, float]:
    """Share of windows whose truth is in the set, overall and per level, and the mean size."""
    sets = [calibration.classes_in(row, classes) for row in probs]
    out: dict[str, float] = {
        "all": round(float(np.mean([t in s for t, s in zip(truth, sets, strict=True)])), 4)
        if truth
        else 0.0,
        "mean_set_size": round(float(np.mean([len(s) for s in sets])), 3) if sets else 0.0,
    }
    for cls in classes:
        rows = [s for t, s in zip(truth, sets, strict=True) if t == cls]
        if rows:
            out[cls] = round(float(np.mean([cls in s for s in rows])), 4)
    return out


__all__ = [
    "FAMILIAR",
    "SERIOUS",
    "choose_guard",
    "coverage",
    "fit_calibration",
    "level_alphas",
]
