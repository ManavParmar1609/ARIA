"""Reporter, critic and comms outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from aria.contracts.base import Claim, Contract, Evidence, EvidenceId, JsonDict, Severity, utcnow
from aria.contracts.retrieval import SimilarIncident, TicketHistoryStats

ReportStatus = Literal["draft", "approved", "rejected", "published"]
Risk = Literal["low", "medium", "high"]


class TimelineEntry(Contract):
    ts: datetime | None = None
    text: str
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class ActionItem(Contract):
    text: str
    runbook_slug: str | None = None
    risk: Risk = "low"
    evidence_ids: list[EvidenceId] = Field(default_factory=list)


class ValidationIssue(Contract):
    code: str
    message: str
    path: str | None = None
    level: Literal["error", "warning"] = "error"


class ValidationResult(Contract):
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    citation_coverage: float = Field(default=0.0, ge=0, le=1)
    checked_claims: int = Field(default=0, ge=0)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.level == "error"]


class IncidentReport(Contract):
    report_id: str
    run_id: str
    version: int = Field(default=1, ge=1)
    title: str
    severity: Severity
    status: ReportStatus = "draft"
    summary: list[Claim] = Field(min_length=1)
    impact: list[Claim] = Field(default_factory=list)
    suspected_cause: list[Claim] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    similar_incidents: list[SimilarIncident] = Field(default_factory=list)
    ticket_history: TicketHistoryStats | None = None
    actions: list[ActionItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    generated_by: Literal["template", "llm"] = "template"
    model: str | None = None
    validation: ValidationResult = Field(default_factory=lambda: ValidationResult(ok=False))
    created_at: datetime = Field(default_factory=utcnow)

    def claims(self) -> list[tuple[str, Claim]]:
        """Every claim with its JSON path, for the critic."""
        out: list[tuple[str, Claim]] = []
        for section in ("summary", "impact", "suspected_cause"):
            for i, claim in enumerate(getattr(self, section)):
                out.append((f"{section}[{i}]", claim))
        return out


class OutboundAction(Contract):
    """A message ARIA proposes to send. Nothing is sent until a reviewer approves it."""

    action_id: str
    kind: Literal["slack", "teams", "webhook", "status_page", "ticket_draft"]
    audience: Literal["responders", "stakeholders", "customers"] = "responders"
    title: str
    body: str
    payload: JsonDict = Field(default_factory=dict)
    status: Literal["proposed", "approved", "rejected", "sent", "failed", "skipped"] = "proposed"
    requires_approval: bool = True
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    result: JsonDict = Field(default_factory=dict)


class ReportEdits(Contract):
    title: str | None = None
    severity: Severity | None = None
    summary: list[str] | None = None
    add_actions: list[str] = Field(default_factory=list)
    note: str | None = None


class ReviewDecision(Contract):
    decision: Literal["approve", "reject", "edit"]
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str | None = None
    edits: ReportEdits | None = None
    approve_actions: list[str] = Field(default_factory=list)
