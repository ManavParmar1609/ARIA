"""Ask ARIA: questions about a run or about incident history, answered only from evidence.

The question is untrusted input. It is fenced in the prompt like log text, and the answer is
held to the report's rules: every statement cites evidence ARIA has, and no number may appear
that the cited evidence lacks. Without an LLM (or when its answer fails those checks) ARIA
returns the most relevant evidence instead of an answer it cannot back.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from aria.config import BudgetConfig
from aria.contracts.base import Evidence, EvidenceKind
from aria.evidence import EvidenceStore
from aria.llm.base import BudgetExceededError, LLMError
from aria.llm.budget import BudgetGuard
from aria.llm.prompts import build_messages
from aria.llm.schemas import AnswerOutput, ClaimOut
from aria.reporting.grounding import ungrounded_numbers
from aria.services import Services
from aria.text import headline

_TERM = re.compile(r"[a-z0-9][a-z0-9_.-]{2,}")
_STOP = frozenset(
    {
        "the", "and", "for", "was", "were", "what", "why", "how", "when", "which", "with",
        "this", "that", "from", "into", "did", "does", "are", "has", "have", "had", "who",
        "whom", "its", "about", "there", "their", "them", "they", "then", "than", "over",
        "under", "any", "all",
    }
)  # fmt: skip
MAX_EVIDENCE = 12
# One question's LLM spending: an answer, a repair and one fallback provider at most.
ASK_BUDGET = BudgetConfig(max_tokens=6_000, max_cost_usd=0.05, max_latency_s=30.0, max_llm_calls=3)


def terms(text: str) -> set[str]:
    return {t for t in _TERM.findall(text.lower()) if t not in _STOP}


def rank(
    question: str, evidence: Sequence[Evidence], *, limit: int = MAX_EVIDENCE
) -> list[Evidence]:
    """Evidence ordered by how many of the question's terms it contains (ties keep order)."""
    wanted = terms(question)
    scored = []
    for position, item in enumerate(evidence):
        text = f"{item.title} {item.detail} {item.source} {item.kind}".lower()
        hits = sum(1 for term in wanted if term in text)
        if hits:
            scored.append((-hits, position, item))
    scored.sort(key=lambda entry: (entry[0], entry[1]))
    return [item for _, _, item in scored[:limit]]


async def memory_evidence(services: Services, question: str, *, limit: int = 6) -> list[Evidence]:
    """Past incidents that match the question, as citable evidence."""
    store = EvidenceStore()
    for incident, hit in (await services.memory.search(question, candidates=limit * 2))[:limit]:
        store.add(
            EvidenceKind.INCIDENT,
            f"Past incident {incident.id}: {incident.title} ({incident.severity}, {incident.system})",
            source="memory.search",
            detail=f"Failure mode: {incident.failure_mode}\nResolution: {incident.resolution}\n"
            f"Summary: {incident.summary}",
            data={
                "incident_id": incident.id,
                "title": headline(incident.title),
                "resolution": incident.resolution,
                "source": incident.source,
                "failure_mode": incident.failure_mode,
                "runbook": incident.runbook_slug,
                "score": round(hit.score, 4),
                "synthetic": incident.synthetic,
            },
            ts=incident.last_seen,
        )
    return store.all()


def _fallback(ranked: Sequence[Evidence]) -> AnswerOutput:
    if not ranked:
        return AnswerOutput(
            answer=[],
            insufficient_evidence=True,
            follow_ups=["Name a run, or ask about a system, component or failure mode."],
        )
    claims = [ClaimOut(text=_plain(item)[:400], evidence_ids=[item.id]) for item in ranked[:3]]
    return AnswerOutput(answer=claims, insufficient_evidence=False, follow_ups=[])


def _plain(item: Evidence) -> str:
    """An answer line without a model: what the evidence says, in words a responder can act on."""
    data = item.data or {}
    if item.kind is EvidenceKind.INCIDENT and data.get("title") and data.get("resolution"):
        if data.get("source") == "run":  # ARIA's own report: what was approved, not what fixed it
            return (
                f"A similar past incident, {data['title']}, was triaged by ARIA; the reviewer "
                f"approved these next steps: {data['resolution']}"
            )
        return (
            f"A similar past incident, {data['title']}, was resolved this way: {data['resolution']}"
        )
    return item.title


def check_answer(output: AnswerOutput, known: dict[str, Evidence]) -> list[str]:
    problems = []
    for i, claim in enumerate(output.answer):
        unknown = [e for e in claim.evidence_ids if e not in known]
        if unknown:
            problems.append(f"answer[{i}] cites unknown evidence {', '.join(unknown)}")
            continue
        loose = ungrounded_numbers(claim.text, [known[e] for e in claim.evidence_ids])
        if loose:
            problems.append(f"answer[{i}] has numbers its evidence lacks: {', '.join(loose[:5])}")
    return problems


async def answer(
    services: Services,
    question: str,
    evidence: Sequence[Evidence],
    *,
    use_llm: bool = True,
) -> tuple[AnswerOutput, list[Evidence], str | None]:
    """The answer, the evidence it may cite, and the model that wrote it (None: retrieval)."""
    ranked = rank(question, evidence)
    known = {item.id: item for item in ranked}
    router = services.router
    if use_llm and router.has_real_llm("ask") and ranked:
        facts = {"evidence_count": len(evidence)}
        # Evidence titles quote log templates and alert names, so they travel fenced.
        quoted = {"ranked_evidence": [{"id": e.id, "summary": e.title} for e in ranked]}
        try:
            result = await router.structured(
                "ask",
                "answer",
                build_messages(
                    "answer",
                    facts,
                    ranked,
                    untrusted={"question": question},
                    untrusted_data=quoted,
                ),
                AnswerOutput,
                validator=lambda output: check_answer(output, known),
                budget=BudgetGuard(ASK_BUDGET),
                temperature=0.0,
                max_tokens=700,
            )
        except (BudgetExceededError, LLMError):
            pass
        else:
            if not check_answer(result.value, known):
                return result.value, ranked, f"{result.provider}/{result.model}"
    return _fallback(ranked), ranked, None
