"""Request and response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from aria.contracts.base import Evidence, Severity
from aria.contracts.inputs import RunOptions
from aria.contracts.report import IncidentReport, ReportEdits
from aria.llm.schemas import ClaimOut

RunId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,64}$")]


class Links(BaseModel):
    self: str
    events: str
    stream: str
    report: str
    review: str


def links_for(run_id: str) -> Links:
    base = f"/api/v1/runs/{run_id}"
    return Links(
        self=base,
        events=f"{base}/events",
        stream=f"{base}/stream",
        report=f"{base}/report",
        review=f"{base}/review",
    )


class RunAccepted(BaseModel):
    run_id: str
    status: str
    links: Links


class RunSummary(BaseModel):
    id: str
    status: str
    trigger: str
    title: str | None = None
    system: str
    severity: str | None = None
    decided_by: str | None = None
    confidence: float | None = None
    auditable: bool | None = None
    latency_ms: float | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    report_id: str | None = None
    parent_run_id: str | None = None
    forked_from_checkpoint: str | None = None
    alert_group_id: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class RunDetail(RunSummary):
    links: Links
    review: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None
    notes: list[str] = Field(default_factory=list)
    replan_reasons: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class RunPage(BaseModel):
    runs: list[RunSummary]
    next_before: datetime | None = None


class ReportOut(BaseModel):
    report: IncidentReport
    markdown: str


class ReviewRequest(BaseModel):
    """A reviewer's decision. With API keys, the reviewer is the authenticated key's name."""

    decision: Literal["approve", "reject", "edit"]
    reviewer: Annotated[str, StringConstraints(min_length=1, max_length=120)] | None = None
    comment: Annotated[str, StringConstraints(max_length=2_000)] | None = None
    edits: ReportEdits | None = None
    approve_actions: list[str] = Field(default_factory=list, max_length=10)


class ForkRequest(BaseModel):
    checkpoint_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    options: dict[str, Any] | None = None
    title: Annotated[str, StringConstraints(max_length=200)] | None = None

    def run_options(self) -> dict[str, Any] | None:
        """Only the options the caller set, validated against ``RunOptions``."""
        if not self.options:
            return None
        RunOptions.model_validate(self.options)
        return dict(self.options)


class Checkpoint(BaseModel):
    checkpoint_id: str
    parent_checkpoint_id: str | None = None
    step: int | None = None
    source: str | None = None
    next: list[str]
    created_at: str | None = None
    status: str | None = None
    severity: str | None = None
    interrupted: bool = False


class AskRequest(BaseModel):
    question: Annotated[str, StringConstraints(min_length=3, max_length=1_000)]
    run_id: RunId | None = None


class AskResponse(BaseModel):
    answer: list[ClaimOut]
    insufficient_evidence: bool
    follow_ups: list[str] = Field(default_factory=list)
    evidence: list[Evidence]
    answered_by: Literal["llm", "retrieval"]
    model: str | None = None


class AlertAccepted(BaseModel):
    alert_group_id: str
    run_id: str | None
    grouped: bool
    alerts: int
    status: str


class IncidentOut(BaseModel):
    incident_id: str
    title: str
    system: str
    failure_mode: str
    severity: Severity
    summary: str
    resolution: str
    runbook_slug: str | None = None
    occurrences: int
    last_seen: datetime | None = None
    source: str
    synthetic: bool
    score: float | None = None


class RunbookStep(BaseModel):
    text: str
    risk: str


class RunbookOut(BaseModel):
    slug: str
    title: str
    risk: str
    systems: list[str]
    failure_modes: list[str]
    when_to_use: str
    diagnose: list[RunbookStep]
    mitigate: list[RunbookStep]
    verify: list[RunbookStep]
    escalate: str


class ProviderOut(BaseModel):
    name: str
    kind: str
    enabled: bool
    chat_model: str | None
    embedding_model: str | None
    verified: bool
    breaker: str
    last_error: str | None
    roles: list[str]


class Me(BaseModel):
    """Who is calling. With no API keys configured the API is open and nobody signs in."""

    name: str
    authenticated: bool
    auth_required: bool


class SettingsOut(BaseModel):
    """The configuration a reviewer may see: limits, guardrails and routing, never secrets."""

    environment: str
    require_approval: bool
    worker_mode: str
    rate_limit_per_minute: int
    budgets: dict[str, Any]
    guardrails: dict[str, Any]
    severity: dict[str, Any]
    retrieval: dict[str, Any]
    investigation: dict[str, Any]
    routing: dict[str, list[str]]
    embeddings: list[str]
    safety: list[str]


class ReviewOut(BaseModel):
    """One human review, as the active-learning queue keeps it."""

    run_id: str
    decision: str
    from_severity: Severity | None = None
    to_severity: Severity | None = None
    reviewer: str
    comment: str | None = None
    failure_mode: str | None = None
    used_for_recalibration: bool
    created_at: datetime


class CalibrationOut(BaseModel):
    """Where the severity model's calibration stands against the reviews gathered so far."""

    model_version: str | None
    trained_version: str | None
    recalibrated: bool
    reviews_in_model: int
    reviewed: int  # approvals and edits that can recalibrate the loaded model
    pending: int  # reviewed incidents since the loaded model was calibrated
    recalibrate_after: int
    check_interval_s: int
    coverage_before: float | None = None
    coverage_after: float | None = None


class FeedbackOut(BaseModel):
    calibration: CalibrationOut
    reviews: list[ReviewOut]


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: bool
    llm: bool
    providers: list[str]
    incidents: int
    runbooks: int
