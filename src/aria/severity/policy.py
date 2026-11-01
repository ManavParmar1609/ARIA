"""The severity decision policy.

1. Floors from rules are absolute: classes less severe than the floor leave the prediction set.
2. A single-class set with calibrated probability at or above the gate (0.85 by default) is
   decided without an LLM. It counts as decided by ``rules`` when a floor fixed it or the rules
   agree, otherwise by ``model``. Both are auditable. Nothing is decided automatically when the
   window is unlike anything the model learned from: the rules then supply the set, and a
   person always confirms.
3. Otherwise an LLM may choose, but only a class inside the set and never below the floor. A
   person confirms when the set is wide, the window is unlike the training data, or the pick is
   below a serious level the set kept possible.
4. With no LLM (none configured, budget spent, or invalid output), the most severe class in the
   set is chosen and flagged for human review: under-triage costs more than over-triage.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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
    # No class cleared the conformal threshold: raw_set holds the model's most likely class and
    # the rules' class, and the policy plans for the more serious.
    set_empty: bool = False
    # Features too far from the model's training data for it to be used; rules decided the set.
    outside_training: list[str] = field(default_factory=list)
    # The miss rate the set allows per level (empty: ``alpha`` for every level), and the
    # calibration that made it: "familiar" (per level), "rules" (no model) or "single" (a model
    # with one threshold for every level).
    alphas: dict[Severity, float] = field(default_factory=dict)
    calibration: str = "familiar"
    # Why a person should confirm even though the model was used (see SeverityEngine._novelty),
    # or "outside_training" when it was not. Any reason rules out an automatic decision.
    novelty: list[str] = field(default_factory=list)

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
        if len(pset) != 1 or self.outside_training or self.novelty:
            return None
        if self.floor_applied():
            return "rules"  # the floor alone settled it
        only = pset[0]
        if self.probabilities.get(only, 0.0) < gate:
            return None
        return "rules" if only == self.rule_severity else "model"


def coverage_words(alphas: Mapping[Severity, float]) -> str:
    """The prediction set's promise in a few words, for evidence and claims.

    One rate for every level reads "90% prediction set"; per-level rates read "prediction set
    (95% coverage for SEV1 and SEV2, 90% for SEV3 and SEV4)".
    """
    rates = sorted({round(1 - a, 4) for a in alphas.values()})
    if len(rates) <= 1:
        words = f"{rates[0] if rates else 0.9:.0%} prediction set"
    else:
        serious = min(1 - alphas.get(s, 1.0) for s in (Severity.SEV1, Severity.SEV2))
        rest = min(1 - alphas.get(s, 1.0) for s in (Severity.SEV3, Severity.SEV4))
        words = f"prediction set ({serious:.0%} coverage for SEV1 and SEV2, {rest:.0%} for SEV3 and SEV4)"
    return words


def torn_words(severity: Severity | str, prediction_set: Iterable[Severity | str]) -> str | None:
    """The levels ARIA could not rule out and the one it plans for, when there are several:
    "ARIA is torn between SEV2 and SEV3 and plans for SEV2". None for a set of one level.

    The planned level can sit outside the set when a ticket's own rating lifted it; the words
    stay true.
    """
    levels = sorted({Severity(level) for level in prediction_set}, key=lambda s: s.rank)
    if len(levels) <= 1:
        return None
    named = [str(level) for level in levels]
    between = f"{', '.join(named[:-1])} and {named[-1]}"
    return f"ARIA is torn between {between} and plans for {Severity(severity)}"


def level_words(severity: Severity | str, prediction_set: Iterable[Severity | str]) -> str:
    """A severity as ARIA states it to a reviewer: the bare level ("SEV2") when the prediction
    set holds one level, and what ARIA is torn between (``torn_words``) when it holds more."""
    return torn_words(severity, prediction_set) or str(Severity(severity))


SERIOUS = frozenset({Severity.SEV1, Severity.SEV2})
NOVELTY_WORDS = {
    "unusual_mix": "its mix of signals is unlike the windows the model learned from",
    "new_patterns": "most of its log patterns are new for this system",
    "empty_set": "no level was likely enough on its own",
    "every_level": "every level stayed possible",
    "new_system": "ARIA has not trained on this system, where its sets miss more often",
}


def _cite(ids: Sequence[str | None]) -> list[str]:
    return [i for i in ids if i][:6]


def _base_claims(pre: Preliminary) -> list[Claim]:
    claims: list[Claim] = []
    if pre.outside_training and pre.model_evidence:
        claims.append(
            Claim(
                text=f"The calibrated model was not used: this window is unlike the ones it "
                f"learned from, so the rules set the choices ({', '.join(pre.prediction_set)}) and "
                "a person confirms the severity.",
                evidence_ids=_cite([pre.model_evidence]),
            )
        )
    elif pre.model_evidence:
        pset = ", ".join(pre.prediction_set)
        words = coverage_words(pre.alphas or dict.fromkeys(SEVERITY_ORDER, pre.alpha))
        text = (
            f"Calibrated model: {pre.top} is most likely (p={pre.confidence:.2f}), but no severity "
            f"is likely enough to enter the {words} on its own."
            if pre.set_empty
            else f"Calibrated model: {pre.top} is most likely (p={pre.confidence:.2f}); the "
            f"{words} is {{{pset}}}."
        )
        claims.append(Claim(text=text, evidence_ids=_cite([pre.model_evidence])))
    reasons = [NOVELTY_WORDS[r] for r in pre.novelty if r in NOVELTY_WORDS]
    if reasons and pre.model_evidence and not pre.outside_training:
        claims.append(
            Claim(
                text=f"A person should confirm this severity: {'; '.join(reasons)}.",
                evidence_ids=_cite([pre.model_evidence]),
            )
        )
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
        "alphas": dict(pre.alphas),
        "calibration": pre.calibration,
        "novelty": list(pre.novelty),
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
            # A person confirms a wide set, a window unlike the training data, and any pick
            # below a serious level the set kept possible: that is where a severe miss hides.
            needs_review=len(pset) >= 3
            or bool(pre.outside_training)
            or bool(pre.novelty)
            or (bool(SERIOUS & set(pset)) and llm_choice not in SERIOUS),
            rationale=[*llm_claims, *_base_claims(pre)][:5],
            **common,
        )
    chosen = pset[0]  # most severe class in the set
    reason = llm_unavailable_reason or "no LLM adjudicator is configured"
    claims = _base_claims(pre)
    if claims:
        claims.append(
            Claim(
                text=(
                    f"No level was likely enough on its own and {reason}, so ARIA planned for the "
                    f"more serious of the model's most likely level and the rules' ({chosen}) and "
                    "flagged it for review."
                    if pre.set_empty
                    else f"Not confident enough to auto-decide and {reason}, so ARIA chose the "
                    f"most severe class in the set ({chosen}) and flagged it for review."
                ),
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
