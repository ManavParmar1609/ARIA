"""Reporter, critic and comms outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

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


# A reviewer's line: each becomes a claim or an action, so it has a claim's bounds.
EditLine = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)]


class ReportEdits(Contract):
    """A reviewer's changes, bounded like the report they change. A bad edit is refused with 422
    when it is sent, instead of failing the run (a summary line too long for a claim) or
    publishing a blank claim or action when it is applied."""

    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    severity: Severity | None = None
    summary: Annotated[list[EditLine], Field(max_length=10)] | None = None  # empty: keep it
    add_actions: Annotated[list[EditLine], Field(max_length=10)] = Field(default_factory=list)
    note: Annotated[str, StringConstraints(max_length=2_000)] | None = None

    def changes_anything(self) -> bool:
        return bool(self.title or self.severity or self.summary or self.add_actions or self.note)


def review_problem(decision: str, edits: ReportEdits | None) -> str | None:
    """Why a decision and its edits do not fit together, or None when they do. Edits only apply
    with "edit"; sent with "approve" or "reject" they would be recorded but never applied."""
    changes = edits is not None and edits.changes_anything()
    if decision == "edit" and not changes:
        return (
            'an "edit" decision needs at least one change: a title, a severity, a summary, '
            "actions to add or a note"
        )
    if decision != "edit" and changes:
        return f'edits apply only with the decision "edit"; send "{decision}" without them'
    return None


class ReviewDecision(Contract):
    decision: Literal["approve", "reject", "edit"]
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str | None = None
    edits: ReportEdits | None = None
    approve_actions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _edits_fit_the_decision(self) -> ReviewDecision:
        if problem := review_problem(self.decision, self.edits):
            raise ValueError(problem)
        return self
