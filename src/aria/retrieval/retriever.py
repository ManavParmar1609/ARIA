"""Agentic retrieval: search, grade the result, and re-plan the query when it is weak.

1. Build a query from the window's own evidence: top error templates, components, keyword
   categories and the investigator's failure-mode hypotheses.
2. Hybrid search (BM25 + embeddings, fused with RRF) over incident memory, scoped to the system.
3. Optionally rerank the candidates with a cross-encoder (NVIDIA NIM rerank) when configured.
4. Grade the result. Below ``min_grade``, re-plan: widen the candidate pool and rewrite the
   query (with the LLM when available, deterministically otherwise), then drop the system
   filter to find analogues on other systems. The best-graded attempt wins, and an analogue's
   grade is discounted, so it wins only over a much weaker match on the system itself.

The grade is a documented heuristic (``grade_hits``), not a learned relevance model; every
attempt is recorded so reviewers can see why ARIA searched again.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.engine import Engine

from aria.config import RetrievalConfig
from aria.contracts.base import EvidenceKind
from aria.contracts.inputs import TicketContext
from aria.contracts.parsing import ParsedBatch
from aria.contracts.retrieval import (
    Hypothesis,
    RetrievalAttempt,
    RetrievalResult,
    RunbookRef,
    SimilarIncident,
    TicketHistoryStats,
)
from aria.evidence import EvidenceStore
from aria.llm.base import BudgetExceededError, LLMError
from aria.llm.budget import BudgetGuard
from aria.llm.prompts import build_messages
from aria.llm.router import LLMRouter
from aria.llm.schemas import QueryRewrite
from aria.observability.logging import get_logger
from aria.parsing.signals import signal_components, signal_templates
from aria.retrieval.hybrid import Hit
from aria.retrieval.memory import IncidentMemory, MemoryIncident
from aria.retrieval.runbooks import Runbook
from aria.retrieval.tickets import ticket_history

log = get_logger(__name__)
_WILDCARD = re.compile(r"<\*>|\b[0-9a-f]{6,}\b|\d+")


@dataclass
class RetrievalQuery:
    system: str
    text: str
    failure_mode_hints: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    template_terms: list[str] = field(default_factory=list)


def _template_terms(template: str) -> list[str]:
    words = list(re.findall(r"[A-Za-z][A-Za-z_]{2,}", _WILDCARD.sub(" ", template)))
    return words[:12]


def build_query(batch: ParsedBatch, hypotheses: Sequence[Hypothesis] = ()) -> RetrievalQuery:
    signal = signal_templates(batch)[:3] or batch.templates[:2]
    terms: list[str] = []
    for template in signal:
        terms.extend(_template_terms(template.template))
    keywords = [
        k for k, v in sorted(batch.features.keyword_hits.items(), key=lambda kv: -kv[1]) if v
    ][:4]
    components = signal_components(batch, 4) or batch.features.components[:4]
    hints = [h.failure_mode for h in hypotheses if h.status in ("open", "supported")][:3]
    if batch.flows.broken and "unfinished_work" not in hints:
        hints.append("unfinished_work")  # units of work that stopped partway (parsing/flows.py)
    text = " ".join([*hints, *components, *keywords, *terms])
    return RetrievalQuery(
        system=batch.system,
        text=text[:400] or batch.system,
        failure_mode_hints=hints,
        components=components,
        keywords=keywords,
        template_terms=terms[:20],
    )


# An analogue from another system is weaker evidence than the system's own history: without
# the discount, a confident match on another system outgrades this system's own incidents.
ANALOGUE_DISCOUNT = 0.6


def grade_hits(
    pairs: Sequence[tuple[MemoryIncident, Hit]],
    hints: Sequence[str],
    *,
    k: int,
    system: str | None = None,
) -> float:
    """0..1: lexical match of the best hit, dense similarity, agreement among the top k, and
    agreement with the investigator's hypotheses (when there are any). A best hit from a system
    other than ``system`` counts for less (``ANALOGUE_DISCOUNT``)."""
    if not pairs:
        return 0.0
    top_incident, top = pairs[0]
    lexical = top.lexical if top.rerank is None else 1 / (1 + math.exp(-top.rerank))
    dense = max(0.0, top.dense)
    modes = Counter(inc.failure_mode for inc, _ in pairs[:k])
    agreement = modes[top_incident.failure_mode] / min(k, len(pairs))
    parts = [(0.4, lexical), (0.25, dense), (0.2, agreement)]
    if hints:
        parts.append((0.15, 1.0 if top_incident.failure_mode in hints else 0.0))
    total = sum(w for w, _ in parts)
    grade = sum(w * v for w, v in parts) / total
    if system is not None and top_incident.system != system:
        grade *= ANALOGUE_DISCOUNT
    return round(grade, 4)


def deterministic_rewrite(query: RetrievalQuery) -> str:
    terms: list[str] = []
    for term in [
        *query.failure_mode_hints,
        *query.components,
        *query.keywords,
        *query.template_terms[:6],
    ]:
        if term and term not in terms:
            terms.append(term)
    return " ".join(terms)[:300] or query.text


class Retriever:
    def __init__(
        self,
        memory: IncidentMemory,
        runbooks: dict[str, Runbook],
        *,
        engine: Engine,
        router: LLMRouter | None,
        config: RetrievalConfig,
    ) -> None:
        self.memory = memory
        self.runbooks = runbooks
        self.engine = engine
        self.router = router
        self.config = config

    async def _rewrite(
        self,
        query: RetrievalQuery,
        attempts: Sequence[RetrievalAttempt],
        *,
        budget: BudgetGuard | None,
        use_llm: bool,
        router: LLMRouter | None = None,
    ) -> tuple[str, str | None]:
        router = router or self.router
        if not (use_llm and router is not None):
            return deterministic_rewrite(query), None
        facts = {"system": query.system, "failure_mode_hints": query.failure_mode_hints}
        # The query, its terms and earlier attempts come from log text: fenced, not context.
        quoted = {
            "query": query.text,
            "components": query.components,
            "keywords": query.keywords,
            "template_terms": query.template_terms,
            "previous_attempts": [a.model_dump(include={"query", "grade"}) for a in attempts],
        }
        try:
            result = await router.structured(
                "retriever",
                "query_rewrite",
                build_messages("query_rewrite", facts, untrusted_data=quoted),
                QueryRewrite,
                budget=budget,
                max_tokens=300,
            )
        except (BudgetExceededError, LLMError):
            return deterministic_rewrite(query), None
        return result.value.query, result.provider

    async def _rerank(self, query: str, pairs: list[tuple[MemoryIncident, Hit]]) -> bool:
        if self.router is None or len(pairs) < 2:
            return False
        result = await self.router.rerank(query, [inc.document().text for inc, _ in pairs])
        if result is None:
            return False
        _, scores = result
        for (_, hit), score in zip(pairs, scores, strict=True):
            hit.rerank = round(float(score), 4)
        pairs.sort(key=lambda pair: -(pair[1].rerank or 0.0))
        return True

    async def search_memory(
        self,
        query: RetrievalQuery,
        *,
        k: int,
        candidates: int,
        widen_level: int = 0,
        budget: BudgetGuard | None = None,
        use_llm: bool = True,
        router: LLMRouter | None = None,
    ) -> tuple[list[tuple[MemoryIncident, Hit]], list[RetrievalAttempt], bool]:
        attempts: list[RetrievalAttempt] = []
        best: list[tuple[MemoryIncident, Hit]] = []
        best_grade, reranked_best = -1.0, False
        text = query.text
        system: str | None = query.system
        pool = max(candidates, self.config.widen_candidates if widen_level else candidates)
        for attempt in range(1, self.config.max_attempts + 1):
            pairs = await self.memory.search(text, system=system, candidates=pool)
            reranked = await self._rerank(text, pairs)
            grade = grade_hits(pairs, query.failure_mode_hints, k=k, system=query.system)
            attempts.append(
                RetrievalAttempt(
                    attempt=attempt,
                    query=text[:300],
                    filters={"system": system} if system else {},
                    candidates=len(pairs),
                    grade=grade,
                    widened=attempt > 1 or widen_level > 0,
                )
            )
            if grade > best_grade:
                best, best_grade, reranked_best = pairs, grade, reranked
            if grade >= self.config.min_grade:
                break
            if attempt == 1:  # widen the pool and rewrite the query
                pool = max(pool, self.config.widen_candidates)
                text, _ = await self._rewrite(
                    query, attempts, budget=budget, use_llm=use_llm, router=router
                )
            else:  # look for analogues on other systems
                system = None
        return best[:k], attempts, reranked_best

    def runbooks_for(self, system: str, modes: Sequence[str], *, limit: int = 3) -> list[Runbook]:
        chosen: list[Runbook] = []
        for mode in modes:
            for runbook in self.runbooks.values():
                if not runbook.generic and mode in runbook.failure_modes and runbook not in chosen:
                    chosen.append(runbook)
        if not chosen:
            chosen = [
                rb for rb in self.runbooks.values() if not rb.generic and system in rb.systems
            ][:1]
        generic = self.runbooks.get("generic-triage")
        if generic is not None and len(chosen) < limit:
            chosen.append(generic)
        return chosen[:limit]

    async def retrieve(
        self,
        query: RetrievalQuery,
        *,
        evidence: EvidenceStore,
        ticket: TicketContext | None = None,
        k: int | None = None,
        candidates: int | None = None,
        widen_level: int = 0,
        budget: BudgetGuard | None = None,
        use_llm: bool = True,
        router: LLMRouter | None = None,
    ) -> RetrievalResult:
        """Similar past incidents and runbooks for ``query``. ``router``, when given, answers
        the query rewrite instead of the retriever's own (a run started with a visitor's key)."""
        k = k or self.config.k
        pairs, attempts, reranked = await self.search_memory(
            query,
            k=k,
            candidates=candidates or self.config.candidates,
            widen_level=widen_level,
            budget=budget,
            use_llm=use_llm,
            router=router,
        )
        incidents: list[SimilarIncident] = []
        for incident, hit in pairs:
            history = self.memory.history(incident)
            eid = evidence.add(
                EvidenceKind.INCIDENT,
                f"Similar incident {incident.id}: {incident.title} ({incident.severity}; "
                f"{history.occurrences}x on {incident.system})",
                source="mcp.search_incidents",
                detail=f"Resolution: {incident.resolution}\nSummary: {incident.summary}",
                data={
                    "incident_id": incident.id,
                    "failure_mode": incident.failure_mode,
                    "score": hit.score,
                    "lexical": hit.lexical,
                    "dense": hit.dense,
                    "rerank": hit.rerank,
                    "occurrences": history.occurrences,
                    "synthetic": incident.synthetic,
                    "runbook": incident.runbook_slug,
                },
                ts=incident.last_seen,
            )
            incidents.append(
                SimilarIncident(
                    incident_id=incident.id,
                    title=incident.title,
                    system=incident.system,
                    failure_mode=incident.failure_mode,
                    severity=incident.severity,
                    score=hit.rerank if hit.rerank is not None and hit.rerank > 0 else hit.score,
                    lexical_score=hit.lexical,
                    dense_score=max(-1.0, min(1.0, hit.dense)),
                    rerank_score=hit.rerank,
                    occurrences=history.occurrences,
                    first_seen=history.first_seen,
                    last_seen=history.last_seen,
                    resolution=incident.resolution,
                    runbook_slug=incident.runbook_slug,
                    components=incident.components[:6],
                    mttr_minutes=history.mttr_minutes,
                    source=incident.source,
                    evidence_id=eid,
                )
            )

        modes = [*query.failure_mode_hints, *(i.failure_mode for i in incidents)]
        # Runbooks for what this window shows (the investigator's hypotheses and the parser's
        # findings) come before those of past incidents that merely look alike.
        hinted = [
            rb
            for mode in query.failure_mode_hints
            for rb in self.runbooks.values()
            if not rb.generic and mode in rb.failure_modes
        ]
        slugs = [i.runbook_slug for i in incidents if i.runbook_slug]
        runbooks: list[Runbook] = []
        for runbook in [*hinted, *(self.runbooks[s] for s in slugs if s in self.runbooks)]:
            if runbook not in runbooks:
                runbooks.append(runbook)
        for extra in self.runbooks_for(query.system, modes):
            if extra not in runbooks:
                runbooks.append(extra)
        refs: list[RunbookRef] = []
        for runbook in runbooks[:3]:
            steps = [
                f"{s.text} [risk: {s.risk}]" if s.risk != "low" else s.text
                for s in runbook.mitigate
            ]
            eid = evidence.add(
                EvidenceKind.RUNBOOK,
                f"Runbook {runbook.slug}: {runbook.title}",
                source="mcp.get_runbook",
                detail="\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)),
                data={
                    "slug": runbook.slug,
                    "risk": runbook.risk,
                    "failure_modes": list(runbook.failure_modes),
                },
            )
            refs.append(
                RunbookRef(
                    slug=runbook.slug,
                    title=runbook.title,
                    failure_modes=list(runbook.failure_modes),
                    steps=steps,
                    risk=runbook.risk,
                    evidence_id=eid,
                )
            )

        tickets: TicketHistoryStats | None = None
        if ticket is not None:
            tickets = ticket_history(self.engine, ticket)
            if tickets is not None:
                eid = evidence.add(
                    EvidenceKind.TICKETS,
                    f"{tickets.n_similar} similar ITSM tickets: SLA breached in "
                    f"{(tickets.sla_breach_rate or 0):.0%}, reopened in {(tickets.reopen_rate or 0):.0%}",
                    source="mcp.ticket_history",
                    detail=(
                        f"matched on {tickets.matched_on or 'all tickets'} (back-off level {tickets.backoff_level}); "
                        f"median resolution {tickets.median_resolution_hours} h, p90 {tickets.p90_resolution_hours} h"
                    ),
                    data=tickets.model_dump(mode="json", exclude={"evidence_id"}),
                )
                tickets = tickets.model_copy(update={"evidence_id": eid})
        best = max((a.grade for a in attempts), default=0.0)
        return RetrievalResult(
            incidents=incidents,
            tickets=tickets,
            runbooks=refs,
            attempts=attempts,
            grade=best,
            reranked=reranked,
        )
