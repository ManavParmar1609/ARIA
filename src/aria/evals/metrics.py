"""Evaluation metrics. Severities are ordinal, so under-triage gets its own measures.

Every point estimate that summarises a sample also has a bootstrap 95% interval
(``bootstrap``), because the evaluation sets are small and a single number would overstate how
precisely they are known.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from itertools import pairwise
from typing import Any

import numpy as np
from sklearn.metrics import cohen_kappa_score

from aria.contracts.base import SEVERITY_ORDER

CLASSES = [str(s) for s in SEVERITY_ORDER]  # SEV1 (most severe) .. SEV4
_RANK = {c: i for i, c in enumerate(CLASSES)}


def accuracy(truth: Sequence[str], pred: Sequence[str]) -> float:
    return float(np.mean([t == p for t, p in zip(truth, pred, strict=True)])) if truth else 0.0


def macro_f1(truth: Sequence[str], pred: Sequence[str]) -> float:
    """Mean F1 over the classes present in truth or prediction (sklearn's macro average with
    those labels), computed from counts because the bootstrap calls it thousands of times."""
    if not truth:
        return 0.0
    scores = []
    for cls in set(truth) | set(pred):
        tp = sum(t == cls and p == cls for t, p in zip(truth, pred, strict=True))
        wrong = sum((t == cls) != (p == cls) for t, p in zip(truth, pred, strict=True))
        scores.append(2 * tp / (2 * tp + wrong))
    return float(np.mean(scores))


def per_class(truth: Sequence[str], pred: Sequence[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for cls in CLASSES:
        tp = sum(t == cls and p == cls for t, p in zip(truth, pred, strict=True))
        fp = sum(t != cls and p == cls for t, p in zip(truth, pred, strict=True))
        fn = sum(t == cls and p != cls for t, p in zip(truth, pred, strict=True))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[cls] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": sum(t == cls for t in truth),
        }
    return out


def confusion(truth: Sequence[str], pred: Sequence[str]) -> list[list[int]]:
    """Rows are the truth, columns the prediction, both SEV1..SEV4."""
    matrix = [[0] * len(CLASSES) for _ in CLASSES]
    for t, p in zip(truth, pred, strict=True):
        matrix[_RANK[t]][_RANK[p]] += 1
    return matrix


def quadratic_kappa(truth: Sequence[str], pred: Sequence[str]) -> float:
    """Agreement that penalises a miss by the square of how many levels it is off."""
    if len(set(truth) | set(pred)) < 2:
        return 1.0 if list(truth) == list(pred) else 0.0
    return float(
        cohen_kappa_score(
            [_RANK[t] for t in truth],
            [_RANK[p] for p in pred],
            labels=list(range(len(CLASSES))),
            weights="quadratic",
        )
    )


def under_triage(truth: Sequence[str], pred: Sequence[str]) -> float:
    """Share of cases rated less severe than they are (the costly direction)."""
    if not truth:
        return 0.0
    return float(np.mean([_RANK[p] > _RANK[t] for t, p in zip(truth, pred, strict=True)]))


def severe_under_triage(truth: Sequence[str], pred: Sequence[str]) -> float:
    """Share of SEV1/SEV2 incidents rated SEV3 or SEV4: an outage treated as routine."""
    serious = [(t, p) for t, p in zip(truth, pred, strict=True) if _RANK[t] <= 1]
    if not serious:
        return 0.0
    return float(np.mean([_RANK[p] >= 2 for _, p in serious]))


def over_triage(truth: Sequence[str], pred: Sequence[str]) -> float:
    if not truth:
        return 0.0
    return float(np.mean([_RANK[p] < _RANK[t] for t, p in zip(truth, pred, strict=True)]))


def expected_calibration_error(
    probabilities: Sequence[Mapping[str, float]], truth: Sequence[str], *, bins: int = 10
) -> float:
    """Top-label ECE: how far stated confidence is from observed accuracy, binned."""
    if not truth:
        return 0.0
    conf = np.array([max(p.values()) for p in probabilities])
    hit = np.array(
        [max(p, key=p.__getitem__) == t for p, t in zip(probabilities, truth, strict=True)]
    )
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for lo, hi in pairwise(edges):
        mask = (conf > lo) & (conf <= hi)
        if mask.any():
            total += mask.mean() * abs(hit[mask].mean() - conf[mask].mean())
    return float(total)


def brier(probabilities: Sequence[Mapping[str, float]], truth: Sequence[str]) -> float:
    if not truth:
        return 0.0
    scores = [
        sum((p.get(c, 0.0) - (1.0 if c == t else 0.0)) ** 2 for c in CLASSES)
        for p, t in zip(probabilities, truth, strict=True)
    ]
    return float(np.mean(scores))


def set_coverage(sets: Sequence[Sequence[str]], truth: Sequence[str]) -> float:
    if not truth:
        return 0.0
    return float(np.mean([t in s for s, t in zip(sets, truth, strict=True)]))


def recall_at_k(ranked: Sequence[Sequence[str]], wanted: Sequence[str], k: int) -> float:
    pairs = [(r, w) for r, w in zip(ranked, wanted, strict=True) if w]
    if not pairs:
        return 0.0
    return float(np.mean([w in list(r)[:k] for r, w in pairs]))


def mean_reciprocal_rank(ranked: Sequence[Sequence[str]], wanted: Sequence[str]) -> float:
    pairs = [(list(r), w) for r, w in zip(ranked, wanted, strict=True) if w]
    if not pairs:
        return 0.0
    return float(np.mean([1.0 / (r.index(w) + 1) if w in r else 0.0 for r, w in pairs]))


def ndcg_at_k(
    ranked: Sequence[Sequence[str]], wanted: Sequence[str], k: int, *, relevant: int | None = None
) -> float:
    """Binary-relevance nDCG@k: a hit shares the wanted label. ``relevant`` is how many relevant
    items exist per query (default ``k``), which sets the ideal ranking."""
    pairs = [(list(r)[:k], w) for r, w in zip(ranked, wanted, strict=True) if w]
    if not pairs:
        return 0.0
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, relevant or k)))
    gains = [sum(1 / math.log2(i + 2) for i, x in enumerate(r) if x == w) for r, w in pairs]
    return float(np.mean([min(1.0, g / ideal) for g in gains]))


def risk_coverage(
    confidence: Sequence[float], correct: Sequence[bool], *, points: Sequence[float] = ()
) -> dict[str, Any]:
    """Selective prediction: keep the most confident share of cases and measure the error rate.

    Returns the error at each requested coverage and the area under the risk-coverage curve
    (AURC, lower is better)."""
    order = sorted(range(len(confidence)), key=lambda i: -confidence[i])
    errors = np.cumsum([0 if correct[i] else 1 for i in order])
    n = len(order)
    if not n:
        return {"points": [], "aurc": 0.0}
    risk = errors / np.arange(1, n + 1)
    chosen = points or (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
    return {
        "points": [
            {"coverage": c, "risk": round(float(risk[max(0, math.ceil(c * n) - 1)]), 4)}
            for c in chosen
        ],
        "aurc": round(float(risk.mean()), 4),
    }


def percentile(values: Sequence[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


def bootstrap(
    metric: Callable[[Sequence[Any], Sequence[Any]], float],
    truth: Sequence[Any],
    pred: Sequence[Any],
    *,
    rounds: int = 1_000,
    seed: int = 7,
) -> tuple[float, float]:
    """A 95% percentile interval for ``metric`` by resampling cases with replacement."""
    if len(truth) < 2:
        value = metric(truth, pred) if truth else 0.0
        return value, value
    rng = np.random.default_rng(seed)
    n = len(truth)
    samples = []
    for _ in range(rounds):
        idx = rng.integers(0, n, n)
        samples.append(metric([truth[i] for i in idx], [pred[i] for i in idx]))
    low, high = np.percentile(samples, [2.5, 97.5])
    return round(float(low), 4), round(float(high), 4)


def classification_report(truth: Sequence[str], pred: Sequence[str]) -> dict[str, Any]:
    return {
        "n": len(truth),
        "accuracy": round(accuracy(truth, pred), 4),
        "accuracy_ci95": bootstrap(accuracy, truth, pred),
        "macro_f1": round(macro_f1(truth, pred), 4),
        "macro_f1_ci95": bootstrap(macro_f1, truth, pred),
        "quadratic_kappa": round(quadratic_kappa(truth, pred), 4),
        "under_triage": round(under_triage(truth, pred), 4),
        "severe_under_triage": round(severe_under_triage(truth, pred), 4),
        "over_triage": round(over_triage(truth, pred), 4),
        "per_class": per_class(truth, pred),
        "confusion": confusion(truth, pred),
    }
