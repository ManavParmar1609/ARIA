"""Applying a reviewer's decision to a report.

A reviewer's words become evidence too: each review is recorded as a ``review`` evidence item,
and every claim or action a reviewer adds cites it, so a published report still has no claim
without a source. A severity change is recorded as a human decision, with ARIA's original rating
kept in the report. A report whose severity ARIA left for a person to confirm says, once
approved, that a person did, and loses the step that asked for it.
"""

from __future__ import annotations

from typing import Any

from aria.contracts.base import Claim, EvidenceKind
from aria.contracts.report import ActionItem, IncidentReport, ReportEdits, ReviewDecision
from aria.contracts.severity import SeverityAssessment
from aria.evidence import EvidenceStore
from aria.reporting.composer import CONFIRM_SEVERITY
from aria.text import headline

AUTO_REVIEWER = "aria:auto"  # the run did not ask for approval (``graph.workflow.review``)


def review_evidence(
    decision: ReviewDecision, report: IncidentReport, evidence: EvidenceStore
) -> str:
    edits = decision.edits or ReportEdits()
    lines = [f"decision: {decision.decision}"]
    if edits.title:
        lines.append(f"title: {edits.title}")
    if edits.severity and edits.severity != report.severity:
        lines.append(f"severity: {report.severity} -> {edits.severity}")
    elif decision.decision != "reject":
        lines.append(f"severity: {report.severity} kept")
    lines += [f"summary: {text}" for text in edits.summary or []]
    lines += [f"action: {text}" for text in edits.add_actions]
    if edits.note:
        lines.append(f"note: {edits.note}")
    if decision.comment:
        lines.append(f"comment: {decision.comment}")
    return evidence.add(
        EvidenceKind.REVIEW,
        f"Review by {decision.reviewer}: {decision.decision}",
        source="reviewer",
        detail="\n".join(lines),
        data={
            "reviewer": decision.reviewer,
            "decision": decision.decision,
            "edits": edits.model_dump(mode="json", exclude_none=True),
            "approved_actions": list(decision.approve_actions),
        },
    )


def apply_review(
    report: IncidentReport,
    severity: SeverityAssessment,
    decision: ReviewDecision,
    evidence: EvidenceStore,
) -> tuple[IncidentReport, SeverityAssessment]:
    """The report and assessment after the review, with the review itself as cited evidence."""
    eid = review_evidence(decision, report, evidence)
    review_item = next(item for item in evidence.new_items() if item.id == eid)
    update: dict[str, Any] = {"evidence": [*report.evidence, review_item]}
    edits = decision.edits if decision.decision == "edit" else None
    if edits is None:
        update.update(_confirmed(report, severity, decision, eid))
        return report.model_copy(update=update), severity

    update["version"] = report.version + 1
    final = edits.severity or report.severity
    if edits.title or final != report.severity:
        # The heading leads with the severity it now has, whichever of the two the reviewer changed.
        update["title"] = f"{final} · {headline(edits.title or report.title)}"[:140]
    summary = list(report.summary)
    if edits.summary:
        # A line the reviewer kept keeps the evidence it cites; a new or reworded one cites the review.
        kept = {claim.text: claim for claim in report.summary}
        summary = [kept.get(text) or Claim(text=text, evidence_ids=[eid]) for text in edits.summary]
    new_severity = severity
    if edits.severity and edits.severity != report.severity:
        # Worded so it does not read like an instruction to a model ("set the severity to ...").
        note = Claim(
            text=f"Reviewer {decision.reviewer} assigned {edits.severity}; "
            f"ARIA's assessment was {report.severity}.",
            evidence_ids=[eid],
        )
        summary = [note, *summary]
        update["severity"] = edits.severity
        new_severity = severity.model_copy(
            update={
                "severity": edits.severity,
                "decided_by": "human",
                "floor": None,  # a reviewer is accountable for going below the rule floor
                "needs_review": False,
                "rationale": [note, *severity.rationale],
            }
        )
    update["summary"] = summary
    if new_severity is severity:  # the reviewer kept ARIA's level
        update.update(
            _confirmed(report.model_copy(update={"summary": summary}), severity, decision, eid)
        )
    if edits.add_actions:
        added = [
            ActionItem(text=text, risk="medium", evidence_ids=[eid]) for text in edits.add_actions
        ]
        update["actions"] = [*update.get("actions", report.actions), *added]
    if edits.note:
        update["open_questions"] = [*report.open_questions, f"Reviewer note: {edits.note}"]
    return report.model_copy(update=update), new_severity


def _confirmed(
    report: IncidentReport, severity: SeverityAssessment, decision: ReviewDecision, eid: str
) -> dict[str, Any]:
    """A report ARIA asked a person to confirm, once one has: its summary says so, citing the
    review, and the step that asked for it goes."""
    unsure = severity.decided_by == "fallback" or severity.needs_review
    if decision.decision == "reject" or decision.reviewer == AUTO_REVIEWER or not unsure:
        return {}
    confirmed = Claim(text=f"A reviewer confirmed {report.severity}.", evidence_ids=[eid])
    return {
        "summary": [*report.summary[:1], confirmed, *report.summary[1:]],
        "actions": [a for a in report.actions if not a.text.startswith(CONFIRM_SEVERITY)],
    }
