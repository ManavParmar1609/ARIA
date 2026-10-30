"""Output schemas the LLM must fill. Each becomes a strict JSON Schema for structured output.

Schemas stay flat and small: every field is required (nullable where optional), so the same
schema works with OpenAI strict mode, Azure OpenAI and NIM guided decoding.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from aria.contracts.base import Contract, EvidenceId, Severity

ShortText = Annotated[str, StringConstraints(min_length=1, max_length=600)]


class ClaimOut(Contract):
    text: ShortText
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=8)


class AdjudicationOutput(Contract):
    """The adjudicator picks a severity from the conformal prediction set and cites why."""

    severity: Severity
    rationale: list[ClaimOut] = Field(min_length=1, max_length=4)
    uncertainty: Annotated[str, StringConstraints(max_length=400)] = ""


class ToolArguments(Contract):
    query: str | None = None
    template_id: str | None = None
    component: str | None = None
    node: str | None = None
    failure_mode: str | None = None
    slug: str | None = None
    limit: int | None = Field(default=None, ge=1, le=50)


class HypothesisUpdate(Contract):
    id: Annotated[str, StringConstraints(pattern=r"^H\d{1,3}$")]
    status: Literal["open", "supported", "refuted", "inconclusive"]
    confidence: float = Field(ge=0, le=1)
    supporting: list[EvidenceId] = Field(default_factory=list, max_length=8)
    refuting: list[EvidenceId] = Field(default_factory=list, max_length=8)


class NewHypothesis(Contract):
    statement: ShortText
    failure_mode: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    component: str | None = None


class ToolRequest(Contract):
    tool: str  # narrowed at call time to the allowlisted tool names
    arguments: ToolArguments = Field(default_factory=ToolArguments)


class InvestigatorStep(Contract):
    """One round: update beliefs, then run read-only tool calls in parallel, or finish."""

    rationale: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    new_hypotheses: list[NewHypothesis] = Field(default_factory=list, max_length=3)
    updates: list[HypothesisUpdate] = Field(default_factory=list, max_length=6)
    calls: list[ToolRequest] = Field(default_factory=list, max_length=5)
    finish: bool = False


class ActionOut(Contract):
    text: ShortText
    runbook_slug: str | None = None
    risk: Literal["low", "medium", "high"] = "low"
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=8)


class NarrativeOutput(Contract):
    title: Annotated[str, StringConstraints(min_length=4, max_length=140)]
    summary: list[ClaimOut] = Field(min_length=1, max_length=5)
    impact: list[ClaimOut] = Field(default_factory=list, max_length=4)
    suspected_cause: list[ClaimOut] = Field(default_factory=list, max_length=4)
    actions: list[ActionOut] = Field(default_factory=list, max_length=6)
    open_questions: list[Annotated[str, StringConstraints(max_length=300)]] = Field(
        default_factory=list, max_length=4
    )


class CriticIssue(Contract):
    path: str  # for example "summary[1]"
    problem: Literal["unsupported", "contradicted", "overstated", "missing_citation", "other"]
    explanation: Annotated[str, StringConstraints(max_length=400)]
    suggested_evidence_ids: list[EvidenceId] = Field(default_factory=list, max_length=6)


class CriticOutput(Contract):
    verdict: Literal["pass", "revise"]
    issues: list[CriticIssue] = Field(default_factory=list, max_length=12)


class MessageDraft(Contract):
    title: Annotated[str, StringConstraints(min_length=1, max_length=140)]
    body: Annotated[str, StringConstraints(min_length=1, max_length=1_500)]
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=10)


class CommsOutput(Contract):
    responders: MessageDraft
    stakeholders: MessageDraft
    status_page: MessageDraft


class AnswerOutput(Contract):
    answer: list[ClaimOut] = Field(default_factory=list, max_length=6)
    insufficient_evidence: bool = False
    follow_ups: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list, max_length=3
    )


class QueryRewrite(Contract):
    query: Annotated[str, StringConstraints(min_length=2, max_length=300)]
    system: str | None = None
    failure_mode: str | None = None


class SafetyOutput(Contract):
    safe: bool
    categories: list[str] = Field(default_factory=list, max_length=8)
    explanation: Annotated[str, StringConstraints(max_length=300)] = ""
