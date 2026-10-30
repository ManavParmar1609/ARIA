"""Retrieval and investigation outputs."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import Field

from aria.contracts.base import Claim, Contract, EvidenceId, JsonDict, Severity


class SimilarIncident(Contract):
    incident_id: str
    title: str
    system: str
    failure_mode: str
    severity: Severity
    score: float = Field(ge=0)
    lexical_score: float = Field(ge=0)
    dense_score: float = Field(ge=-1, le=1)
    rerank_score: float | None = None
    occurrences: int = Field(ge=1)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    resolution: str
    runbook_slug: str | None = None
    components: list[str] = Field(default_factory=list)  # where its signal was, strongest first
    mttr_minutes: float | None = Field(default=None, ge=0)
    source: Literal["memory", "curated", "run"]
    evidence_id: EvidenceId | None = None

    def applies_to(self, system: str, components: Iterable[str]) -> bool:
        """Whether this past incident can stand for a cause here: it comes from the same system,
        or its signal was on a component this window logs. A kernel panic on a supercomputer
        explains nothing about a web app's errors, however close the words or the vectors.
        "generic" names no system, only an unknown log format, so there only a component counts."""
        present = set(components)
        same_system = self.system == system and system != "generic"
        return same_system or any(c in present for c in self.components)


class TicketHistoryStats(Contract):
    """Outcomes of historically similar ITSM tickets (UCI ServiceNow event log)."""

    matched_on: dict[str, str]
    backoff_level: int = Field(ge=0)
    n_similar: int = Field(ge=0)
    sla_breach_rate: float | None = Field(default=None, ge=0, le=1)
    reopen_rate: float | None = Field(default=None, ge=0, le=1)
    mean_reassignments: float | None = Field(default=None, ge=0)
    median_resolution_hours: float | None = Field(default=None, ge=0)
    p90_resolution_hours: float | None = Field(default=None, ge=0)
    top_assignment_groups: list[str] = Field(default_factory=list)
    top_closed_codes: list[str] = Field(default_factory=list)
    evidence_id: EvidenceId | None = None


class RunbookRef(Contract):
    slug: str
    title: str
    failure_modes: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    risk: Literal["low", "medium", "high"] = "low"
    evidence_id: EvidenceId | None = None


class RetrievalAttempt(Contract):
    attempt: int = Field(ge=1)
    query: str
    filters: dict[str, str] = Field(default_factory=dict)
    candidates: int = Field(ge=0)
    grade: float = Field(ge=0, le=1)
    widened: bool = False


class RetrievalResult(Contract):
    incidents: list[SimilarIncident] = Field(default_factory=list)
    tickets: TicketHistoryStats | None = None
    runbooks: list[RunbookRef] = Field(default_factory=list)
    attempts: list[RetrievalAttempt] = Field(default_factory=list)
    grade: float = Field(default=0.0, ge=0, le=1)
    reranked: bool = False


class ToolCallRecord(Contract):
    """Audit record of one MCP tool call."""

    call_id: str
    agent: str
    tool: str
    arguments: JsonDict = Field(default_factory=dict)
    ok: bool
    summary: str = ""
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    duration_ms: float = Field(ge=0)


class Hypothesis(Contract):
    id: str = Field(pattern=r"^H\d{1,3}$")
    statement: str
    failure_mode: str
    component: str | None = None
    status: Literal["open", "supported", "refuted", "inconclusive"] = "open"
    confidence: float = Field(ge=0, le=1)
    supporting: list[EvidenceId] = Field(default_factory=list)
    refuting: list[EvidenceId] = Field(default_factory=list)


class Investigation(Contract):
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    steps: int = Field(default=0, ge=0)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    leading_hypothesis: str | None = None
    summary: list[Claim] = Field(default_factory=list)
    stopped_reason: str = "not_started"
