"""Parser agent output."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from aria.contracts.base import Contract, EvidenceId


class LogEvent(Contract):
    idx: int = Field(ge=0)
    line_no: int | None = None
    ts: datetime | None = None
    node: str | None = None
    component: str | None = None
    level: str | None = None
    message: str
    template_id: str
    flags: list[str] = Field(default_factory=list)


class TemplateStat(Contract):
    template_id: str
    template: str
    count: int = Field(ge=1)
    levels: dict[str, int] = Field(default_factory=dict)
    nodes: int = Field(ge=0)
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    error_like: bool = False
    novel: bool = False
    sample_idx: list[int] = Field(default_factory=list)
    evidence_id: EvidenceId


class WindowFeatures(Contract):
    """Signals the severity rules and model read. All are computed, never generated."""

    n_events: int = Field(ge=0)
    n_templates: int = Field(ge=0)
    duration_s: float = Field(ge=0)
    events_per_min: float = Field(ge=0)
    level_counts: dict[str, int] = Field(default_factory=dict)
    error_events: int = Field(ge=0)
    error_ratio: float = Field(ge=0, le=1)
    keyword_hits: dict[str, int] = Field(default_factory=dict)
    burst_score: float = Field(ge=0)
    peak_errors_per_min: float = Field(ge=0)
    distinct_nodes: int = Field(ge=0)
    error_nodes: int = Field(ge=0)
    node_spread: float = Field(ge=0, le=1)
    novel_templates: int = Field(ge=0)
    novel_error_templates: int = Field(ge=0)
    components: list[str] = Field(default_factory=list)
    critical_components: list[str] = Field(default_factory=list)
    max_component_criticality: float = Field(ge=0, le=1)
    persistence_s: float = Field(ge=0)


class RedactionSummary(Contract):
    counts: dict[str, int] = Field(default_factory=dict)
    pseudonyms: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class InjectionFinding(Contract):
    line_idx: int = Field(ge=0)
    pattern: str
    excerpt: str
    score: float = Field(ge=0, le=1)


class SafetyVerdict(Contract):
    provider: str
    safe: bool
    categories: list[str] = Field(default_factory=list)


class GuardReport(Contract):
    redactions: RedactionSummary = Field(default_factory=RedactionSummary)
    injections: list[InjectionFinding] = Field(default_factory=list)
    safety: SafetyVerdict | None = None
    truncated_lines: int = Field(default=0, ge=0)
    dropped_lines: int = Field(default=0, ge=0)


class ParsedBatch(Contract):
    system: str
    n_raw_lines: int = Field(ge=0)
    events: list[LogEvent] = Field(default_factory=list)
    templates: list[TemplateStat] = Field(default_factory=list)
    features: WindowFeatures
    guard: GuardReport = Field(default_factory=GuardReport)
    shards: int = Field(default=1, ge=1)
