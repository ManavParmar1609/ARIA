"""The severity decision policy.

1. Floors from rules are absolute: classes less severe than the floor leave the prediction set.
2. A single-class set with calibrated probability at or above the gate (0.85 by default) is
   decided without an LLM. It counts as decided by ``rules`` when a floor fixed it or the rules
   agree, otherwise by ``model``. Both are auditable.
3. Otherwise an LLM may choose, but only a class inside the set and never below the floor.
4. With no LLM (none configured, budget spent, or invalid output), the most severe class in the
   set is chosen and flagged for human review: under-triage costs more than over-triage.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from aria.contracts.base import SEVERITY_ORDER, Claim, Severity
from aria.contracts.severity import DecidedBy, RuleHit, SeverityAssessment


@dataclass
class Preliminary:
    """Everything the deterministic stages produced, before anyone adjudicates."""

    rule_severity: Severity
    rule_scores: dict[Severity, float]
    rule_hits: list[RuleHit]
    floor: Severity | None
    probabilities: dict[Severity, float]
    raw_set: list[Severity]
    alpha: float
    model_version: str
    rule_evidence: list[str] = field(default_factory=list)
    model_evidence: str | None = None
    conformal: bool = True
    set_empty: bool = False  # no class cleared the conformal threshold (raw_set is the argmax)

    @property
    def prediction_set(self) -> list[Severity]:
        """The conformal set with the floor applied; never empty."""
        allowed = [s for s in self.raw_set if self.floor is None or s.rank <= self.floor.rank]
        if not allowed:
            allowed = (
                [self.floor]
                if self.floor is not None
                else [max(self.raw_set, key=lambda s: -s.rank)]
            )
        return sorted(set(allowed), key=lambda s: s.rank)

    @property
    def top(self) -> Severity:
        allowed = self.prediction_set
        return max(allowed, key=lambda s: (round(self.probabilities.get(s, 0.0), 9), -s.rank))

    @property
    def confidence(self) -> float:
        return float(self.probabilities.get(self.top, 0.0))

    def floor_applied(self) -> bool:
        """True when the floor removed classes from (or replaced) the conformal set.

        A set already at or above the floor is left as it is, so the floor decided nothing.
        """
        if self.floor is None:
            return False
        floor = self.floor
        return any(s.rank > floor.rank for s in self.raw_set)

    def auto_decision(self, gate: float) -> DecidedBy | None:
        pset = self.prediction_set
        if len(pset) != 1:
            return None
        if self.floor_applied():
            return "rules"  # the floor alone settled it
        only = pset[0]
        if self.probabilities.get(only, 0.0) < gate:
            return None
        return "rules" if only == self.rule_severity else "model"


def _cite(ids: Sequence[str | None]) -> list[str]:
    return [i for i in ids if i][:6]


def _base_claims(pre: Preliminary) -> list[Claim]:
    claims: list[Claim] = []
    if pre.model_evidence:
        pset = ", ".join(pre.prediction_set)
        text = (
            f"Calibrated model: {pre.top} is most likely (p={pre.confidence:.2f}), but no severity "
            f"is likely enough to enter the {1 - pre.alpha:.0%} prediction set on its own."
            if pre.set_empty
            else f"Calibrated model: {pre.top} is most likely (p={pre.confidence:.2f}); the "
            f"{1 - pre.alpha:.0%} prediction set is {{{pset}}}."
        )
        claims.append(Claim(text=text, evidence_ids=_cite([pre.model_evidence])))
    floors = [hit for hit in pre.rule_hits if hit.effect == "floor"]
    if floors and pre.floor is not None:
        claims.append(
            Claim(
                text=f"Safety floor {pre.floor}: {floors[0].title.lower()}.",
                evidence_ids=_cite(floors[0].evidence_ids),
            )
        )
    scoring = sorted(
        (h for h in pre.rule_hits if h.effect == "score"),
        key=lambda h: (h.severity.rank, -h.weight),
    )
    if scoring:
        top = scoring[0]
        claims.append(
            Claim(
                text=f"Rules point to {pre.rule_severity}; strongest signal: {top.title.lower()} ({top.detail}).",
                evidence_ids=_cite(top.evidence_ids),
            )
        )
    return [c for c in claims if c.evidence_ids]


def decide(
    pre: Preliminary,
    *,
    gate: float,
    llm_choice: Severity | None = None,
    llm_claims: Sequence[Claim] = (),
    llm_unavailable_reason: str | None = None,
) -> SeverityAssessment:
    pset = pre.prediction_set
    common: dict[str, Any] = {
        "rule_severity": pre.rule_severity,
        "rule_scores": pre.rule_scores,
        "rule_hits": pre.rule_hits,
        "probabilities": {s: round(pre.probabilities.get(s, 0.0), 6) for s in SEVERITY_ORDER},
        "prediction_set": pset,
        "set_empty": pre.set_empty,
        "alpha": pre.alpha,
        "floor": pre.floor,
        "model_version": pre.model_version,
    }
    auto = pre.auto_decision(gate)
    if auto is not None:
        return SeverityAssessment(
            severity=pset[0],
            decided_by=auto,
            confidence=float(pre.probabilities.get(pset[0], 0.0)),
            auditable=True,
            needs_review=False,
            rationale=_base_claims(pre),
            **common,
        )
    if llm_choice is not None:
        if llm_choice not in pset:
            msg = f"LLM choice {llm_choice} is outside the prediction set {pset}"
            raise ValueError(msg)
        return SeverityAssessment(
            severity=llm_choice,
            decided_by="llm",
            confidence=float(pre.probabilities.get(llm_choice, 0.0)),
            auditable=False,
            needs_review=len(pset) >= 3,
            rationale=[*llm_claims, *_base_claims(pre)][:5],
            **common,
        )
    chosen = pset[0]  # most severe class in the set
    reason = llm_unavailable_reason or "no LLM adjudicator is configured"
    claims = _base_claims(pre)
    if claims:
        claims.append(
            Claim(
                text=f"Not confident enough to auto-decide and {reason}, so ARIA chose the most "
                f"severe class in the set ({chosen}) and flagged it for review.",
                evidence_ids=claims[0].evidence_ids,
            )
        )
    return SeverityAssessment(
        severity=chosen,
        decided_by="fallback",
        confidence=float(pre.probabilities.get(chosen, 0.0)),
        auditable=True,
        needs_review=True,
        rationale=claims,
        **common,
    )
