"""Graph state for a triage run.

Every value is JSON-shaped (dicts, lists, strings, numbers), so a checkpoint is portable across
processes and versions and loads without unpickling anything. Nodes validate what they read into
the Pydantic contracts and dump what they write.

Channels written by parallel branches have reducers: evidence is merged by id, budget usage is
summed from per-node deltas, and audit lists are appended to.
"""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict

from aria.contracts.base import Evidence
from aria.contracts.run import BudgetUsage

Json = dict[str, Any]
_COUNTERS = ("tokens_in", "tokens_out", "llm_calls", "tool_calls", "steps")


def merge_evidence(current: list[Json] | None, new: list[Json] | None) -> list[Json]:
    """Union by evidence id, ordered by id number (ids are unique across nodes and branches)."""
    by_id = {item["id"]: item for item in current or []}
    for item in new or []:
        by_id[item["id"]] = item
    return sorted(by_id.values(), key=lambda item: int(item["id"][1:]))


def _ts(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def add_usage(current: Json | None, delta: Json | None) -> Json:
    """Sum budget usage reported by nodes; each parallel branch reports its own delta."""
    if not current:
        return dict(delta or {})
    if not delta:
        return dict(current)
    out = dict(current)
    for key in _COUNTERS:
        out[key] = int(current.get(key, 0)) + int(delta.get(key, 0))
    out["cost_usd"] = round(float(current.get("cost_usd", 0)) + float(delta.get("cost_usd", 0)), 6)
    out["cost_known"] = bool(current.get("cost_known", True)) and bool(
        delta.get("cost_known", True)
    )
    out["exhausted"] = list(
        dict.fromkeys([*current.get("exhausted", []), *delta.get("exhausted", [])])
    )
    starts = [s for s in (current.get("started_at"), delta.get("started_at")) if s]
    if starts:
        out["started_at"] = min(starts, key=_ts)
    return out


def usage_delta(before: BudgetUsage, after: BudgetUsage) -> Json:
    """What a node spent, as a delta the ``add_usage`` reducer can sum."""
    delta: Json = {key: getattr(after, key) - getattr(before, key) for key in _COUNTERS}
    delta["cost_usd"] = round(after.cost_usd - before.cost_usd, 6)
    delta["cost_known"] = after.cost_known
    delta["exhausted"] = [e for e in after.exhausted if e not in before.exhausted]
    return delta


class TriageState(TypedDict, total=False):
    run_id: str
    request: Json  # TriageRequest
    plan: Json  # Plan
    status: str  # RunStatus
    shards: Annotated[list[Json], operator.add]  # parse workers' results, cleared after merge
    batch: Json  # ParsedBatch
    severity: Json  # SeverityAssessment
    ticket: Json | None  # TicketAssessment
    retrieval: Json  # RetrievalResult
    investigation: Json  # Investigation
    replan_reasons: list[str]
    report: Json  # IncidentReport
    report_meta: Json  # how the report was written: LLM or template, critic, fallbacks
    actions: list[Json]  # OutboundAction
    review: Json  # ReviewDecision
    evidence: Annotated[list[Json], merge_evidence]
    budget: Annotated[Json, add_usage]
    tool_calls: Annotated[list[Json], operator.add]
    notes: Annotated[list[str], operator.add]
    errors: Annotated[list[Json], operator.add]


def evidence_of(state: TriageState) -> list[Evidence]:
    return [Evidence.model_validate(item) for item in state.get("evidence", [])]


def dump_evidence(items: list[Evidence]) -> list[Json]:
    return [item.model_dump(mode="json") for item in items]
