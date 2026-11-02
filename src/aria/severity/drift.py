"""Has a system's severity mix shifted, and are severe misses running above the promise?

**Drift.** ARIA compares the levels it decided on a system's most recent runs with the levels it
decided on that system's earlier runs, using the population stability index (PSI). A fixed PSI
cut-off such as 0.1 or 0.25 means very different things at 30 runs and at 3,000, so the cut-off
here is the one sampling noise alone would exceed only 5% of the time: under no shift, PSI is
approximately ``(1/n + 1/m)`` times a chi-square variable with ``bins - 1`` degrees of freedom
(Yurdakul, "Statistical properties of population stability index", 2018).

**The severe-miss alarm.** Blind checks (a person rating an incident before seeing ARIA's level)
arrive one at a time, and someone looks after each one, so a test with a fixed sample size would
be fooled by the looking. :func:`severe_miss_alarm` tracks the checks of serious incidents in
arrival order with a test martingale: the likelihood of the misses so far under miss rates above
the promised one, averaged over them, against their likelihood at exactly the promise. Under any
true rate at or below the promise that is a nonnegative supermartingale, so by Ville's inequality
it ever reaches ``1 / alpha`` with probability at most ``alpha`` over the whole future of the
sequence (Ville, 1939; Robbins' mixture martingales, 1970; Howard, Ramdas, McAuliffe and Sekhon,
"Time-uniform, nonparametric, nonasymptotic confidence sequences", Annals of Statistics, 2021;
Ramdas, Grünwald, Vovk and Shafer, "Game-theoretic statistics and safe anytime-valid inference",
Statistical Science, 2023). The alarm may be read after every check and still means what it says.

A shift or an alarm is a prompt to look, not a verdict: new kinds of incidents, a changed system,
or a calibration that no longer fits all show up the same way. The alarm recommends recalibration
or retraining; it changes nothing by itself.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from typing import Any

from scipy.special import betainc, betaln
from scipy.stats import chi2

LEVELS = ("SEV1", "SEV2", "SEV3", "SEV4")
MIN_RUNS = 40  # fewer, and both halves are too small to say anything
MAX_PER_HALF = 200
# The alarm's chance of ever sounding while the promise holds, over an endless run of checks.
ALARM_ALPHA = 0.05


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


# --- a sequential alarm on severe misses ---------------------------------------------------------


def severe_miss_evidence(misses: int, checks: int, epsilon: float) -> float:
    """How strongly ``misses`` severe misses in ``checks`` checks of serious incidents speak
    against a miss rate of at most ``epsilon``.

    The likelihood of the sequence under every miss rate above ``epsilon``, averaged over them
    (a flat prior on ``(epsilon, 1]``), divided by its likelihood at exactly ``epsilon``:
    Robbins' mixture likelihood ratio. Each rate's ratio is a nonnegative supermartingale under
    any true rate at or below ``epsilon``, so their average is one too. 1 with no checks; below 1
    when the checks speak for the promise.
    """
    if checks <= 0:
        return 1.0
    a, b = misses + 1, checks - misses + 1
    # The integral of p^misses (1 - p)^(checks - misses) over (epsilon, 1] is B(a, b) times the
    # upper tail of the Beta(a, b) distribution beyond epsilon, I_{1 - epsilon}(b, a).
    tail = float(betainc(b, a, 1.0 - epsilon))
    if tail <= 0.0:
        return 0.0
    log_mixture = float(betaln(a, b)) + math.log(tail) - math.log1p(-epsilon)
    log_null = misses * math.log(epsilon) + (checks - misses) * math.log1p(-epsilon)
    return math.exp(log_mixture - log_null)


def severe_miss_alarm(
    misses: Sequence[bool], *, epsilon: float, alpha: float = ALARM_ALPHA
) -> dict[str, Any]:
    """Follow blind checks of serious incidents in arrival order and say whether the share ARIA
    rated SEV3 or SEV4 has exceeded the promised ``epsilon`` with confidence.

    ``misses`` holds one flag per check of an incident the person rated SEV1 or SEV2, oldest
    first: True where ARIA's level was SEV3 or SEV4. The alarm sounds the first time the evidence
    (:func:`severe_miss_evidence`) reaches ``1 / alpha`` and stays up: an anytime-valid test
    rejects once, so later checks cannot withdraw it, though the current evidence may fall back.
    ``p_value`` is ``1 / peak``, valid whenever it is read. The alarm recommends recalibration or
    retraining and changes nothing by itself.
    """
    if not 0.0 < epsilon < 1.0:
        msg = f"the promised severe-miss rate must be between 0 and 1, not {epsilon}"
        raise ValueError(msg)
    threshold = 1.0 / alpha
    evidence = peak = 1.0
    raised_at: int | None = None
    count = 0
    for i, missed in enumerate(misses, start=1):
        count += int(bool(missed))
        evidence = severe_miss_evidence(count, i, epsilon)
        peak = max(peak, evidence)
        if raised_at is None and evidence >= threshold:
            raised_at = i
    n = len(misses)
    return {
        "checks": n,
        "misses": count,
        "rate": round(count / n, 4) if n else 0.0,
        "promised": epsilon,
        "evidence": round(evidence, 3),
        "peak": round(peak, 3),
        "threshold": round(threshold, 2),
        "raised": raised_at is not None,
        "raised_at": raised_at,
        "p_value": round(min(1.0, 1.0 / peak), 4),
    }


__all__ = [
    "ALARM_ALPHA",
    "LEVELS",
    "MIN_RUNS",
    "level_drift",
    "psi",
    "psi_critical",
    "severe_miss_alarm",
    "severe_miss_evidence",
]
