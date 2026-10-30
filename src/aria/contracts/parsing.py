"""Parser agent output."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    components: list[str] = Field(default_factory=list)  # most frequent first, at most 3
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
    # Many incidents only log at WARN, so warnings get their own spread, peak and novelty.
    warn_nodes: int = Field(default=0, ge=0)
    peak_warnings_per_min: float = Field(default=0.0, ge=0)
    novel_warn_templates: int = Field(default=0, ge=0)
    components: list[str] = Field(default_factory=list)
    critical_components: list[str] = Field(default_factory=list)
    max_component_criticality: float = Field(ge=0, le=1)
    persistence_s: float = Field(ge=0)
    # Units of work (an HDFS block, a task attempt) followed from start to finish, and how many
    # broke off partway or took a step almost no other unit takes (see parsing/flows.py).
    flows_checked: int = Field(default=0, ge=0)
    broken_flows: int = Field(default=0, ge=0)
    broken_flow_ratio: float = Field(default=0.0, ge=0, le=1)


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


class FlowPair(Contract):
    """Two steps that came in equal numbers on almost every unit of a kind in the window."""

    kind: str
    steps: list[str] = Field(min_length=2, max_length=2)
    units: int = Field(ge=0)
    support: float = Field(ge=0, le=1)


class BrokenUnit(Contract):
    kind: str
    key: str
    problem: Literal["mismatch", "unusual_step"]
    reason: str
    # Template ids: the step seen more often then the one seen less (mismatch), or the rare step.
    steps: list[str] = Field(default_factory=list)
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    lines: list[int] = Field(default_factory=list)  # 0-based line indices, at most 12
    evidence_id: EvidenceId | None = None


class FlowCheck(Contract):
    """Units of work the parser followed from start to finish (config/flows.yaml)."""

    units: dict[str, int] = Field(default_factory=dict)  # units seen, by kind
    checked: dict[str, int] = Field(default_factory=dict)  # units judged, by kind
    broken: int = Field(default=0, ge=0)
    settle_s: dict[str, float] = Field(default_factory=dict)
    pairs: list[FlowPair] = Field(default_factory=list)
    examples: list[BrokenUnit] = Field(default_factory=list)
    broken_keys: list[str] = Field(default_factory=list)  # every broken unit, at most 2,000
    evidence_id: EvidenceId | None = None


class ParsedBatch(Contract):
    system: str
    n_raw_lines: int = Field(ge=0)
    events: list[LogEvent] = Field(default_factory=list)
    templates: list[TemplateStat] = Field(default_factory=list)
    features: WindowFeatures
    guard: GuardReport = Field(default_factory=GuardReport)
    shards: int = Field(default=1, ge=1)
    # Known templates novelty was judged against; 0 means no history, so nothing is "novel".
    template_history: int = Field(default=0, ge=0)
    flows: FlowCheck = Field(default_factory=FlowCheck)
