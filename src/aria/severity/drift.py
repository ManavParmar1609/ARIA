"""Has a system's severity mix shifted? A label-free drift check per system.

ARIA compares the levels it decided on a system's most recent runs with the levels it decided on
that system's earlier runs, using the population stability index (PSI). A fixed PSI cut-off such
as 0.1 or 0.25 means very different things at 30 runs and at 3,000, so the cut-off here is the
one sampling noise alone would exceed only 5% of the time: under no shift, PSI is approximately
``(1/n + 1/m)`` times a chi-square variable with ``bins - 1`` degrees of freedom (Yurdakul, "Statistical
properties of population stability index", 2018).

A shift is a prompt to look, not a verdict: new kinds of incidents, a changed system, or a
calibration that no longer fits all show up the same way.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from typing import Any

from scipy.stats import chi2

LEVELS = ("SEV1", "SEV2", "SEV3", "SEV4")
MIN_RUNS = 40  # fewer, and both halves are too small to say anything
MAX_PER_HALF = 200


def psi(reference: Sequence[str], recent: Sequence[str], bins: Sequence[str] = LEVELS) -> float:
    """Population stability index between two samples of levels (half a count added to every
    bin, so an empty bin does not make it infinite)."""
    ref, new = Counter(reference), Counter(recent)
    n_ref, n_new = len(reference) + 0.5 * len(bins), len(recent) + 0.5 * len(bins)
    total = 0.0
    for b in bins:
        p = (ref[b] + 0.5) / n_ref
        q = (new[b] + 0.5) / n_new
        total += (q - p) * math.log(q / p)
    return total


def psi_critical(n_ref: int, n_new: int, bins: int = len(LEVELS), level: float = 0.95) -> float:
    """The PSI that sampling noise alone exceeds with probability ``1 - level``."""
    return float(chi2.ppf(level, bins - 1)) * (1.0 / max(n_ref, 1) + 1.0 / max(n_new, 1))


def level_drift(levels: Sequence[str]) -> dict[str, Any] | None:
    """Earlier half against recent half of one system's decided levels, oldest first.

    None when there are too few runs to compare.
    """
    usable = [level for level in levels if level in LEVELS]
    if len(usable) < MIN_RUNS:
        return None
    half = min(len(usable) // 2, MAX_PER_HALF)
    reference, recent = usable[:half], usable[-half:]
    value = psi(reference, recent)
    critical = psi_critical(len(reference), len(recent))
    return {
        "runs": len(usable),
        "compared": half,
        "reference": {b: Counter(reference)[b] for b in LEVELS},
        "recent": {b: Counter(recent)[b] for b in LEVELS},
        "psi": round(value, 4),
        "critical": round(critical, 4),
        "shifted": value > critical,
    }


__all__ = ["LEVELS", "MIN_RUNS", "level_drift", "psi", "psi_critical"]
