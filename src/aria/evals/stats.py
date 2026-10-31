"""Statistics that say no more than the data hold.

Small evaluation slices support weaker claims than their point estimates suggest: with eight
severe windows and no misses, the severe-miss rate is only shown to be below about 31%. These
helpers give exact bounds for counts, intervals that do not collapse at 0/n, paired tests for
"is A better than B on the same cases", corrections for testing several things at once, and
resampling by incident or system rather than by window, because windows from one incident are
not independent.

References: Clopper and Pearson (1934); Brown, Cai and DasGupta, Statistical Science (2001);
McNemar (1947) in its exact binomial form; Holm (1979); Blasiok and Nakkiran, "Smooth ECE"
(2023).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
from scipy.stats import beta, binom, norm

SEVERE = frozenset({"SEV1", "SEV2"})
RANK = {"SEV1": 0, "SEV2": 1, "SEV3": 2, "SEV4": 3}


def upper_bound(hits: int, n: int, level: float = 0.95) -> float:
    """The exact one-sided upper confidence bound for a proportion (Clopper-Pearson).

    "No more than this, with this confidence": 0 misses in 8 gives about 0.31, 0 in 59 about
    0.05. With no cases it is 1: the data say nothing.
    """
    if n <= 0:
        return 1.0
    if hits >= n:
        return 1.0
    return float(beta.ppf(level, hits + 1, n - hits))


def wilson(hits: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """The Wilson score interval for a proportion: well behaved at 0/n and n/n."""
    if n <= 0:
        return 0.0, 1.0
    z = float(norm.ppf(1 - (1 - level) / 2))
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, float(centre - half)), min(1.0, float(centre + half))


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs.

    ``only_a``: cases A got right and B got wrong; ``only_b`` the reverse. Under "no difference"
    each discordant case is a fair coin. Fewer than six discordant pairs can never reach p < 0.05.
    """
    n = only_a + only_b
    if n == 0:
        return 1.0
    return float(min(1.0, 2 * binom.cdf(min(only_a, only_b), n, 0.5)))


def holm(pvalues: Mapping[str, float]) -> dict[str, float]:
    """Holm's step-down adjustment: controls the chance of any false finding across the family."""
    order = sorted(pvalues, key=lambda k: pvalues[k])
    m = len(order)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, key in enumerate(order):
        running = max(running, min(1.0, (m - i) * pvalues[key]))
        adjusted[key] = running
    return {k: adjusted[k] for k in pvalues}


def severe_misses(truth: Sequence[str], pred: Sequence[str]) -> tuple[int, int]:
    """(misses, severe cases): truly SEV1/SEV2 windows rated SEV3 or SEV4."""
    severe = [(t, p) for t, p in zip(truth, pred, strict=True) if t in SEVERE]
    return sum(1 for _, p in severe if p not in SEVERE), len(severe)


def over_triage(truth: Sequence[str], pred: Sequence[str]) -> tuple[int, int]:
    """(raised, cases): windows rated more serious than their label."""
    pairs = list(zip(truth, pred, strict=True))
    return sum(1 for t, p in pairs if RANK[p] < RANK[t]), len(pairs)


def macro_mae(truth: Sequence[str], pred: Sequence[str]) -> float:
    """Mean ordinal error per true class, averaged over classes.

    Predicting the majority class everywhere does not score well, unlike plain mean error under
    imbalance (Baccianella, Esuli and Sebastiani, 2009).
    """
    by_class: dict[str, list[int]] = defaultdict(list)
    for t, p in zip(truth, pred, strict=True):
        by_class[t].append(abs(RANK[t] - RANK[p]))
    if not by_class:
        return 0.0
    return float(np.mean([np.mean(errors) for errors in by_class.values()]))


def nll(probabilities: Sequence[Mapping[str, float]], truth: Sequence[str]) -> float:
    """Mean negative log-likelihood of the true class."""
    if not truth:
        return 0.0
    picked = [max(1e-12, float(p.get(t, 0.0))) for p, t in zip(probabilities, truth, strict=True)]
    return float(-np.mean(np.log(picked)))


def smooth_ece(
    confidences: Sequence[float], correct: Sequence[bool], bandwidth: float = 0.05
) -> float:
    """Smoothed expected calibration error of the top label.

    A kernel estimate of accuracy at each confidence, compared with the confidence itself and
    averaged over cases. Unlike binned ECE it does not move when bin edges move.
    """
    c = np.asarray(confidences, dtype=np.float64)
    y = np.asarray(correct, dtype=np.float64)
    if c.size == 0:
        return 0.0
    weights = np.exp(-0.5 * ((c[:, None] - c[None, :]) / bandwidth) ** 2)
    smoothed = (weights @ y) / weights.sum(axis=1)
    return float(np.mean(np.abs(smoothed - c)))


def cluster_bootstrap(
    metric: Callable[[Sequence[Any], Sequence[Any]], float],
    truth: Sequence[Any],
    pred: Sequence[Any],
    groups: Sequence[str],
    *,
    rounds: int = 1_000,
    seed: int = 7,
    level: float = 0.95,
) -> tuple[float, float]:
    """A percentile interval for ``metric`` that resamples whole groups (incidents or systems).

    Windows of one incident are not independent; resampling them one by one overstates the
    certainty. With a single group there is nothing to resample, and the interval is the value.
    """
    by_group: dict[str, list[int]] = defaultdict(list)
    for i, g in enumerate(groups):
        by_group[g].append(i)
    keys = sorted(by_group)
    value = metric(truth, pred) if truth else 0.0
    if len(keys) < 2:
        return value, value
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(rounds):
        picked = [i for k in rng.choice(keys, size=len(keys)) for i in by_group[str(k)]]
        samples.append(metric([truth[i] for i in picked], [pred[i] for i in picked]))
    tail = (1 - level) / 2 * 100
    low, high = np.percentile(samples, [tail, 100 - tail])
    return float(low), float(high)


def paired_bootstrap(
    metric: Callable[[Sequence[Any], Sequence[Any]], float],
    truth: Sequence[Any],
    pred_a: Sequence[Any],
    pred_b: Sequence[Any],
    groups: Sequence[str],
    *,
    rounds: int = 1_000,
    seed: int = 7,
) -> dict[str, float]:
    """The difference ``metric(A) - metric(B)`` on the same cases, with a group-resampled 95%
    interval: both methods see the same resample, so case difficulty cancels out."""
    by_group: dict[str, list[int]] = defaultdict(list)
    for i, g in enumerate(groups):
        by_group[g].append(i)
    keys = sorted(by_group)
    delta = metric(truth, pred_a) - metric(truth, pred_b) if truth else 0.0
    if len(keys) < 2:
        return {"delta": delta, "low": delta, "high": delta}
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(rounds):
        picked = [i for k in rng.choice(keys, size=len(keys)) for i in by_group[str(k)]]
        t = [truth[i] for i in picked]
        diffs.append(
            metric(t, [pred_a[i] for i in picked]) - metric(t, [pred_b[i] for i in picked])
        )
    low, high = np.percentile(diffs, [2.5, 97.5])
    return {"delta": float(delta), "low": float(low), "high": float(high)}


def compare(
    truth: Sequence[str], pred_a: Sequence[str], pred_b: Sequence[str]
) -> dict[str, float | int]:
    """Exact McNemar on correctness, and on missing a severe window, for two methods."""
    right_a = [t == p for t, p in zip(truth, pred_a, strict=True)]
    right_b = [t == p for t, p in zip(truth, pred_b, strict=True)]
    only_a = sum(a and not b for a, b in zip(right_a, right_b, strict=True))
    only_b = sum(b and not a for a, b in zip(right_a, right_b, strict=True))
    severe = [i for i, t in enumerate(truth) if t in SEVERE]
    miss_a = [pred_a[i] not in SEVERE for i in severe]
    miss_b = [pred_b[i] not in SEVERE for i in severe]
    # "A misses fewer": cases B missed and A caught, against the reverse.
    caught_only_a = sum(mb and not ma for ma, mb in zip(miss_a, miss_b, strict=True))
    caught_only_b = sum(ma and not mb for ma, mb in zip(miss_a, miss_b, strict=True))
    return {
        "right_only_a": only_a,
        "right_only_b": only_b,
        "p_correct": round(mcnemar_exact(only_a, only_b), 4),
        "severe_caught_only_a": caught_only_a,
        "severe_caught_only_b": caught_only_b,
        "p_severe": round(mcnemar_exact(caught_only_a, caught_only_b), 4),
    }


__all__ = [
    "SEVERE",
    "cluster_bootstrap",
    "compare",
    "holm",
    "macro_mae",
    "mcnemar_exact",
    "nll",
    "over_triage",
    "paired_bootstrap",
    "severe_misses",
    "smooth_ece",
    "upper_bound",
    "wilson",
]
