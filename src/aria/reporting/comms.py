"""Incident communications: drafts for responders, stakeholders and the status page.

Drafts are proposals only (``OutboundAction`` with ``requires_approval=True``); nothing is sent
until a reviewer approves it. Each audience has its own rules:

* responders: technical and specific, citing the report's evidence;
* stakeholders: business impact in plain words, with no internal identifiers;
* customers (status page): calm, no internal identifiers and no speculation about causes.

An LLM may polish the deterministic drafts, but a polished draft that breaks its audience's
rules is dropped in favour of the deterministic one.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from aria.contracts.base import SEVERITY_DESCRIPTIONS, Severity
from aria.contracts.report import IncidentReport, OutboundAction
from aria.llm.base import BudgetExceededError, LLMError
from aria.llm.budget import BudgetGuard
from aria.llm.prompts import build_messages
from aria.llm.router import LLMRouter
from aria.llm.schemas import CommsOutput, MessageDraft
from aria.reporting.grounding import validate_external_text
from aria.reporting.writer import cited_evidence
from aria.security.safety import check_text
from aria.text import headline

AUDIENCE = {"responders": "responders", "stakeholders": "stakeholders", "status_page": "customers"}
KIND = {"responders": "slack", "stakeholders": "webhook", "status_page": "status_page"}
_IMPACT_WORDS = {
    Severity.SEV1: "a major outage",
    Severity.SEV2: "a significant disruption",
    Severity.SEV3: "a limited issue",
    Severity.SEV4: "a minor issue",
}


# A service name as monitoring labels give it: a few words of letters, digits and . _ / -,
# with no sentence, link or markup in it. Only such a name is written into a message.
_SERVICE_NAME = re.compile(r"[A-Za-z0-9][\w./-]*(?: [\w./-]+){0,4}")
_MAX_SERVICE_CHARS = 48


def is_service_name(text: str) -> bool:
    """Whether ``text`` reads as a service name, not a sentence someone slipped into a label.

    Every audience's message uses the same name, so it must also be fit to leave the team: a
    domain, a host name or another internal identifier is not."""
    return (
        len(text) <= _MAX_SERVICE_CHARS
        and _SERVICE_NAME.fullmatch(text) is not None
        and re.search(r"\.(?:\s|$)", text) is None
        and not validate_external_text(text, audience="customers")
    )


def action_id(report_id: str, key: str) -> str:
    """Stable per report and audience, so a re-run proposes the same action ids for review."""
    return "act-" + hashlib.sha256(f"{report_id}:{key}".encode()).hexdigest()[:12]


@dataclass
class CommsOutcome:
    actions: list[OutboundAction]
    polished_by: str | None = None
    rejected: dict[str, list[str]] = field(default_factory=dict)


def deterministic_drafts(
    report: IncidentReport, *, service: str, run_url: str
) -> dict[str, MessageDraft]:
    ids = [e.id for e in cited_evidence(report)][:10] or [report.evidence[0].id]
    bullets = [f"• {c.text}" for c in report.summary[:3]]
    if report.suspected_cause:
        bullets.append(f"• Suspected: {report.suspected_cause[0].text}")
    if report.actions:
        bullets.append(f"• Next step: {report.actions[0].text}")
    # Report titles already lead with the severity ("SEV3 · ..."); say it once, in brackets.
    responders = MessageDraft(
        title=f"[{report.severity}] {headline(report.title)}"[:140],
        body=("\n".join(bullets) + f"\nReport: {run_url}")[:1_500],
        evidence_ids=ids,
    )
    impact = _IMPACT_WORDS[report.severity]
    stakeholders = MessageDraft(
        title=f"Incident update: {service}"[:140],
        body=(
            f"We are responding to {impact} affecting {service}. "
            f"Severity is {report.severity} ({SEVERITY_DESCRIPTIONS[report.severity].split(':', 1)[0].lower()}). "
            "Engineers are investigating and will share the next update within 30 minutes."
        ),
        evidence_ids=ids[:3],
    )
    status_page = MessageDraft(
        title=f"Investigating issues with {service}"[:140],
        body=(
            f"We are investigating an issue affecting {service}. Some requests may fail or respond "
            "slowly. We will post an update within 30 minutes."
        ),
        evidence_ids=ids[:2],
    )
    return {"responders": responders, "stakeholders": stakeholders, "status_page": status_page}


def _problems(key: str, draft: MessageDraft, known: set[str]) -> list[str]:
    problems = [f"cites unknown evidence {e}" for e in draft.evidence_ids if e not in known]
    if AUDIENCE[key] != "responders":
        problems += validate_external_text(f"{draft.title}\n{draft.body}", audience=AUDIENCE[key])
    return problems


async def draft_comms(
    report: IncidentReport,
    *,
    service: str,
    run_url: str,
    router: LLMRouter | None = None,
    budget: BudgetGuard | None = None,
    use_llm: bool = True,
    safety_check: bool = False,
) -> CommsOutcome:
    drafts = deterministic_drafts(report, service=service, run_url=run_url)
    known = {e.id for e in report.evidence}
    outcome = CommsOutcome(actions=[])
    if use_llm and router is not None and router.chain("comms"):
        facts = {"severity": str(report.severity)}
        # The report and drafts quote logs and alert labels: they go to the model fenced.
        quoted = {
            "report": {
                "title": report.title,
                "service": service,
                "summary": [c.model_dump() for c in report.summary],
                "actions": [a.text for a in report.actions[:3]],
            },
            "drafts": {k: v.model_dump() for k, v in drafts.items()},
        }
        try:
            result = await router.structured(
                "comms",
                "comms",
                build_messages("comms", facts, cited_evidence(report)[:12], untrusted_data=quoted),
                CommsOutput,
                budget=budget,
                temperature=0.3,
                max_tokens=1_200,
            )
            polished = {
                "responders": result.value.responders,
                "stakeholders": result.value.stakeholders,
                "status_page": result.value.status_page,
            }
            outcome.polished_by = f"{result.provider}/{result.model}"
            for key, candidate in polished.items():
                problems = _problems(key, candidate, known)
                if not problems and safety_check:
                    verdict = await check_text(
                        router, f"{candidate.title}\n{candidate.body}", budget=budget
                    )
                    if not verdict.safe:
                        problems = [verdict.describe()]
                if problems:
                    outcome.rejected[key] = problems
                else:
                    drafts[key] = candidate
        except (BudgetExceededError, LLMError):
            pass
    for key, draft in drafts.items():
        problems = _problems(key, draft, known)
        if problems:  # deterministic drafts should never fail; keep them out if they somehow do
            outcome.rejected.setdefault(key, []).extend(problems)
            continue
        outcome.actions.append(_action(report, key, draft))
    return outcome


def _action(report: IncidentReport, key: str, draft: MessageDraft) -> OutboundAction:
    return OutboundAction(
        action_id=action_id(report.report_id, key),
        kind=KIND[key],  # type: ignore[arg-type]
        audience=AUDIENCE[key],  # type: ignore[arg-type]
        title=draft.title,
        body=draft.body,
        payload={"text": f"*{draft.title}*\n{draft.body}"} if KIND[key] == "slack" else {},
        evidence_ids=draft.evidence_ids,
    )


def redraft(
    actions: Sequence[OutboundAction], report: IncidentReport, *, service: str, run_url: str
) -> list[OutboundAction]:
    """The actions rewritten from the reviewed report. Used when a reviewer changed its severity or
    title: a draft written for the old facts must not go out under the new ones."""
    drafts = {
        action_id(report.report_id, key): (key, draft)
        for key, draft in deterministic_drafts(report, service=service, run_url=run_url).items()
    }
    rewritten: list[OutboundAction] = []
    for action in actions:
        found = drafts.get(action.action_id)
        rewritten.append(
            action
            if found is None
            else _action(report, *found).model_copy(update={"status": action.status})
        )
    return rewritten
