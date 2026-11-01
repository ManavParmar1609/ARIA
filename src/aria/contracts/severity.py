"""Severity agent output."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from aria.contracts.base import Claim, Contract, EvidenceId, Severity

DecidedBy = Literal["rules", "model", "llm", "fallback", "human"]


class RuleHit(Contract):
    rule_id: str
    title: str
    effect: Literal["score", "floor"]
    severity: Severity
    weight: float = Field(ge=0)
    detail: str = ""
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class SeverityAssessment(Contract):
    """How severe the incident is, how sure ARIA is, and who decided."""

    severity: Severity
    decided_by: DecidedBy
    rule_severity: Severity
    rule_scores: dict[Severity, float]
    rule_hits: list[RuleHit] = Field(default_factory=list)
    probabilities: dict[Severity, float]
    prediction_set: list[Severity] = Field(min_length=1)
    # True when no class cleared the conformal threshold: the set then holds only the most likely
    # class as a stand-in, and says "the model does not know", not "the model is sure".
    set_empty: bool = False
    alpha: float = Field(gt=0, lt=1)
    # The miss rate the set allows per level: serious levels get a tighter one. Empty for older
    # assessments and rules-only sets, where ``alpha`` applies to every level.
    alphas: dict[Severity, float] = Field(default_factory=dict)
    # Which calibration made the set: "familiar" (per level), "rules" (no model was used) or
    # "single" (an older model with one threshold for every level).
    calibration: Literal["familiar", "rules", "single"] = "familiar"
    # Why a person should confirm the level even if the model was confident: the window is
    # beyond the training data's range, its mix of signals or its share of new log patterns is
    # unusual, the set is empty or holds every level, or the model never trained on the system.
    novelty: list[
        Literal[
            "outside_training",
            "unusual_mix",
            "new_patterns",
            "empty_set",
            "every_level",
            "new_system",
        ]
    ] = Field(default_factory=list)
    floor: Severity | None = None
    confidence: float = Field(ge=0, le=1)
    auditable: bool
    needs_review: bool = False
    rationale: list[Claim] = Field(default_factory=list)
    model_version: str = "unversioned"

    @model_validator(mode="after")
    def _consistent(self) -> SeverityAssessment:
        total = sum(self.probabilities.values())
        if self.probabilities and not 0.98 <= total <= 1.02:
            msg = f"probabilities must sum to 1 (got {total:.3f})"
            raise ValueError(msg)
        if self.floor is not None and self.severity.rank > self.floor.rank:
            msg = f"severity {self.severity} is below the safety floor {self.floor}"
            raise ValueError(msg)
        if self.decided_by == "llm" and self.auditable:
            msg = "an LLM-decided severity is not auditable by rules alone"
            raise ValueError(msg)
        return self


class TicketAssessment(Contract):
    """Priority and SLA-breach risk for an ITSM ticket, from the model trained on UCI history."""

    predicted_priority: str
    severity: Severity
    probabilities: dict[str, float]
    prediction_set: list[str] = Field(min_length=1)
    sla_breach_risk: float | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    model_version: str = "unversioned"
