"""Shared building blocks for every contract.

Contracts forbid unknown fields so a malformed handoff (or LLM output) fails loudly at the
boundary instead of flowing silently into the next agent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

EVIDENCE_ID_PATTERN = r"^E\d{1,5}$"
EvidenceId = Annotated[str, StringConstraints(pattern=EVIDENCE_ID_PATTERN)]
JsonDict = dict[str, Any]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    """Base for every handoff payload."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Severity(StrEnum):
    """Incident severity. SEV1 is the most severe."""

    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"

    @property
    def rank(self) -> int:
        """0 for SEV1 (most severe) through 3 for SEV4."""
        return SEVERITY_ORDER.index(self)

    @classmethod
    def from_rank(cls, rank: int) -> Severity:
        return SEVERITY_ORDER[max(0, min(rank, len(SEVERITY_ORDER) - 1))]

    def more_severe(self, other: Severity) -> Severity:
        return self if self.rank <= other.rank else other

    def escalate(self, steps: int = 1) -> Severity:
        return Severity.from_rank(self.rank - steps)


SEVERITY_ORDER: list[Severity] = [Severity.SEV1, Severity.SEV2, Severity.SEV3, Severity.SEV4]

SEVERITY_DESCRIPTIONS: dict[Severity, str] = {
    Severity.SEV1: "Critical: widespread outage or data-loss risk; page now.",
    Severity.SEV2: "High: major degradation or a failing critical component.",
    Severity.SEV3: "Moderate: contained errors with limited user impact.",
    Severity.SEV4: "Low: informational or noise; no action needed now.",
}


class Claim(Contract):
    """One statement in a report, tied to the evidence that supports it."""

    text: Annotated[str, StringConstraints(min_length=1, max_length=800)]
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class EvidenceKind(StrEnum):
    LOG = "log"
    TEMPLATE = "template"
    FEATURE = "feature"
    RULE = "rule"
    MODEL = "model"
    ALERT = "alert"
    INCIDENT = "incident"
    TICKETS = "tickets"
    RUNBOOK = "runbook"
    TOOL = "tool"
    HYPOTHESIS = "hypothesis"
    FEEDBACK = "feedback"  # reviewer corrections from earlier runs (long-term memory)
    REVIEW = "review"  # what this run's reviewer said or changed


class Evidence(Contract):
    """A citable fact produced by a tool or a deterministic computation."""

    id: EvidenceId
    kind: EvidenceKind
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    detail: Annotated[str, StringConstraints(max_length=4_000)] = ""
    source: str
    data: JsonDict = Field(default_factory=dict)
    ts: datetime | None = None
