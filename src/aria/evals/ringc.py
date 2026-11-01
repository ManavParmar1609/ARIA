"""Shared measures for the ring C suites: data from domains ARIA was never tuned on.

Ring C answers "does ARIA hold on real data nobody tuned on?". Its suites (security alerts,
microservice faults, Kubernetes incidents, issue-tracker priority) only measure: no rule, lexicon
entry, threshold, prompt or model may change because of what they show, or the suite must be
stamped as used for tuning, with the date, and its numbers moved to a post hoc section.

Every rate carries an exact (Clopper-Pearson) interval, since the slices are small; a miss rate
also carries its exact one-sided 95% upper bound, the honest form of "at most" for a gate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from scipy.stats import beta
from sklearn.metrics import roc_auc_score

from aria.contracts.base import Severity
from aria.contracts.inputs import AlertSignal, RunOptions, TriageRequest
from aria.contracts.parsing import ParsedBatch, WindowFeatures
from aria.evals import metrics as m
from aria.evals.pipeline import EvalEnvironment
from aria.evals.severity import keyword_severity
from aria.evidence import EvidenceStore
from aria.parsing.signals import signal_components
from aria.severity.engine import SeverityEngine
from aria.severity.policy import decide

SEVERE = {"SEV1", "SEV2"}  # a page
FLAGGED = {"SEV1", "SEV2", "SEV3"}  # worth a person's look
# ARIA's levels as a ranking score: higher is more severe.
ORDINAL = {"SEV1": 4.0, "SEV2": 3.0, "SEV3": 2.0, "SEV4": 1.0}
STAMP = {
    "ring": "C",
    "tuning": "untouched: no rule, lexicon entry, threshold or model was changed for this data",
}
_PREFIX = re.compile(r"^ts-")
_SUFFIX = re.compile(r"(-?service)$")
_POD = re.compile(r"-[0-9a-f]{6,10}(-[0-9a-z]{5})?$")
_NON_ALNUM = re.compile(r"[^0-9a-z]")


def share(hits: int, n: int) -> dict[str, Any]:
    return {
        "hits": hits,
        "of": n,
        "share": round(hits / n, 4) if n else 0.0,
        "ci95": m.exact_interval(hits, n),
    }


def upper_bound(hits: int, n: int, level: float = 0.95) -> float:
    """The exact one-sided upper bound on a rate seen as ``hits`` of ``n``: with no misses in n
    cases the bound is 1 - (1 - level)^(1/n), the exact rule of three."""
    if n <= 0:
        return 1.0
    if hits >= n:
        return 1.0
    return round(float(beta.ppf(level, hits + 1, n - hits)), 4)


def miss_rate(missed: int, n: int) -> dict[str, Any]:
    return {**share(missed, n), "upper95": upper_bound(missed, n)}


def _auroc(truth: Sequence[bool], scores: Sequence[float]) -> float:
    return float(roc_auc_score(truth, scores)) if len(set(truth)) == 2 else 0.5


def ranking(truth: Sequence[bool], scores: Sequence[float]) -> dict[str, Any]:
    """How well ``scores`` rank the positive cases above the others (AUROC: 0.5 is chance),
    with a bootstrap 95% interval over cases."""
    return {
        "auroc": round(_auroc(truth, scores), 4),
        "auroc_ci95": m.bootstrap(_auroc, list(truth), list(scores)),
        "positives": sum(bool(t) for t in truth),
        "n": len(truth),
    }


def judge(
    engine: SeverityEngine,
    features: WindowFeatures,
    *,
    system: str,
    alerts: Sequence[AlertSignal] = (),
) -> dict[str, Any]:
    """ARIA's offline severity for one window, with the rules alone, the model alone and the
    keyword rule beside it. ``system`` is the name ARIA would see in production: one it never
    trained on sends the window to a person, as it would in a real deployment."""
    pre = engine.preliminary(features, system=system, alerts=alerts, evidence=EvidenceStore())
    decision = decide(pre, gate=engine.gate, llm_unavailable_reason="offline evaluation")
    probabilities = {str(k): float(v) for k, v in pre.probabilities.items()}
    return {
        "severity": str(decision.severity),
        "rules": str(pre.rule_severity),
        "model": max(probabilities, key=probabilities.__getitem__),
        "keyword": keyword_severity(features),
        "decided_by": decision.decided_by,
        "needs_review": decision.needs_review,
        "severe_probability": round(
            probabilities.get("SEV1", 0.0) + probabilities.get("SEV2", 0.0), 6
        ),
        "prediction_set": [str(s) for s in pre.prediction_set],
        "fired": sorted({hit.rule_id for hit in pre.rule_hits}),
    }


def service_key(name: str | None) -> str:
    """A service's name reduced for matching across conventions: 'ts-preserve-service',
    'PreserveService' and 'preserve' all become 'preserve'; pod hashes are dropped."""
    text = (name or "").strip().lower()
    text = _POD.sub("", text)
    text = _PREFIX.sub("", text)
    text = _SUFFIX.sub("", text)
    return _NON_ALNUM.sub("", text)


def rank_of(candidates: Sequence[str], wanted: Sequence[str]) -> int | None:
    """The 1-based position of the first candidate naming a wanted service, or None."""
    keys = {service_key(w) for w in wanted if service_key(w)}
    for position, candidate in enumerate(candidates, start=1):
        if service_key(candidate) in keys:
            return position
    return None


def localisation(ranks: Sequence[int | None], *, top: int = 3) -> dict[str, Any]:
    n = len(ranks)
    return {
        "top1": share(sum(1 for r in ranks if r == 1), n),
        f"top{top}": share(sum(1 for r in ranks if r is not None and r <= top), n),
        "named_anywhere": share(sum(1 for r in ranks if r is not None), n),
    }


def candidates(values: dict[str, Any]) -> list[str]:
    """The services ARIA points at, in its order: the leading hypothesis's component, the other
    hypotheses' components by confidence, then the components carrying the window's signal."""
    investigation = values.get("investigation") or {}
    hypotheses = list(investigation.get("hypotheses") or [])
    leading = investigation.get("leading_hypothesis")
    hypotheses.sort(key=lambda h: (h.get("id") != leading, -float(h.get("confidence") or 0.0)))
    out: list[str] = []
    for hypothesis in hypotheses:
        component = hypothesis.get("component")
        if component and component not in out:
            out.append(str(component))
    batch = values.get("batch")
    if batch:
        for component in signal_components(ParsedBatch.model_validate(batch)):
            if component not in out:
                out.append(component)
    return out


async def triage(
    env: EvalEnvironment,
    *,
    system: str,
    title: str,
    lines: Sequence[str],
    alerts: Sequence[AlertSignal] = (),
) -> dict[str, Any]:
    """One offline run, end to end, to the review pause; scored, then deleted (a run's
    checkpoints hold every line it read)."""
    outcome = await env.runner.start(
        TriageRequest(
            system=system,
            title=title[:200],
            logs=list(lines),
            alerts=list(alerts),
            options=RunOptions(use_llm=False),
        ),
        trigger="eval",
    )
    values = (await env.runner.snapshot(outcome.run_id)).values
    await env.runner.delete(outcome.run_id)
    assessment = values.get("severity") or {}
    probabilities = assessment.get("probabilities") or {}
    investigation = values.get("investigation") or {}
    leading = next(
        (
            h
            for h in investigation.get("hypotheses", [])
            if h.get("id") == investigation.get("leading_hypothesis")
        ),
        None,
    )
    severity = str(assessment.get("severity", ""))
    return {
        "severity": severity,
        "flagged": severity in FLAGGED,
        "paged": severity in SEVERE,
        "rules": str(assessment.get("rule_severity", "")),
        "decided_by": str(assessment.get("decided_by", "")),
        "needs_review": bool(assessment.get("needs_review")),
        "severe_probability": round(
            float(probabilities.get("SEV1", 0.0)) + float(probabilities.get("SEV2", 0.0)), 6
        ),
        "leading_mode": (leading or {}).get("failure_mode") or "none",
        "candidates": candidates(values)[:6],
    }


def by_level(rows: Sequence[dict[str, Any]], key: str = "severity") -> dict[str, int]:
    """How many rows ARIA put at each level, most severe first."""
    return {level: sum(1 for r in rows if r.get(key) == level) for level in m.CLASSES}


def severity_value(level: str) -> Severity | None:
    try:
        return Severity(level)
    except ValueError:
        return None
