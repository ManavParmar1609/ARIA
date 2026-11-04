"""The nearest past incidents a person reviewed, as examples for the severity adjudicator.

Incident memory holds every published run (source ``run``), and the feedback store holds every
review a person gave (aria.graph.workflow records one per reviewed run, under its system and
failure mode, with the level ARIA proposed and the level the person set). An incident is an
example when both hold it: it is near this window, it came from a run, and a person reviewed
that run. Seeded and curated incidents are never examples: nobody rated them, and neither is a
run published unattended.

Nearness is lexical (BM25 over the memory index), which costs no model call: the recall step
already searches memory with embeddings, and this search must not double that spend. The text
of each example is redacted again before it leaves here; the adjudicator fences it.
"""

from __future__ import annotations

from typing import Any

from langgraph.store.base import BaseStore

from aria.contracts.base import Severity
from aria.retrieval.memory import IncidentMemory, incident_run_id
from aria.security.redaction import Redactor
from aria.severity.adjudicator import ReviewedExample
from aria.text import clip

TITLE_CHARS = 160
SUMMARY_CHARS = 400


def _level(value: Any) -> Severity | None:
    try:
        return Severity(str(value)) if value else None
    except ValueError:
        return None


async def _reviews(store: BaseStore, system: str, limit: int) -> dict[str, dict[str, Any]]:
    """The reviews people gave on ``system``, by the run they reviewed."""
    items = await store.asearch(("feedback", system), limit=limit)
    return {
        str(item.value["run_id"]): item.value
        for item in items
        if isinstance(item.value, dict) and item.value.get("run_id")
    }


async def reviewed_examples(
    memory: IncidentMemory,
    store: BaseStore | None,
    *,
    query: str,
    system: str,
    limit: int = 3,
    candidates: int = 12,
    redactor: Redactor | None = None,
    max_reviews: int = 500,
) -> list[ReviewedExample]:
    """Up to ``limit`` of the nearest incidents on ``system`` that came from a run a person
    reviewed, each with the level the person set. Empty without a feedback store or a query."""
    if store is None or not query.strip():
        return []
    hits = memory.index.search(
        query, candidates=candidates, where=lambda meta: bool(meta.get("system") == system)
    )
    from_runs = [
        (memory.incidents[hit.id], hit)
        for hit in hits
        if hit.id in memory.incidents and memory.incidents[hit.id].source == "run"
    ]
    if not from_runs:
        return []
    reviews = await _reviews(store, system, max_reviews)
    redactor = redactor or Redactor()
    examples: list[ReviewedExample] = []
    for incident, hit in from_runs:
        review = reviews.get(incident_run_id(incident.id))
        level = _level(review.get("to")) if review is not None else None
        if review is None or level is None:
            continue
        examples.append(
            ReviewedExample(
                incident_id=incident.id,
                title=clip(redactor.redact(incident.title), TITLE_CHARS),
                summary=clip(redactor.redact(incident.summary), SUMMARY_CHARS),
                failure_mode=incident.failure_mode,
                severity=level,
                aria_severity=_level(review.get("from")),
                decision=str(review.get("decision") or "approve"),
                similarity=round(float(hit.score), 4),
            )
        )
        if len(examples) == limit:
            break
    return examples
