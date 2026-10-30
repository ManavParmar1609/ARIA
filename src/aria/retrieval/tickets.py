"""Outcomes of similar ITSM tickets from the UCI ServiceNow event log.

The UCI log holds anonymised codes ("Category 26", "Symptom 491") and no free text, so tickets
are matched on field equality with a back-off: category + subcategory + symptom, then category
+ subcategory, then category, then all tickets. The first level with enough tickets wins, and
the result says which level that was. When the request carries an open time, only tickets
opened before it are used, so evaluations never peek at the future.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from aria.contracts.inputs import TicketContext
from aria.contracts.retrieval import TicketHistoryStats
from aria.db.engine import session_scope
from aria.db.models import ItsmIncidentRow

LEVELS: tuple[tuple[str, ...], ...] = (
    ("category", "subcategory", "symptom"),
    ("category", "subcategory"),
    ("category",),
    (),
)


def _rate(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def ticket_history(
    engine: Engine, ticket: TicketContext, *, min_n: int = 30, before: datetime | None = None
) -> TicketHistoryStats | None:
    cutoff = before or ticket.opened_at
    with session_scope(engine) as session:
        total = session.scalar(select(func.count()).select_from(ItsmIncidentRow)) or 0
        if not total:
            return None
        for level, keys in enumerate(LEVELS):
            values = {key: getattr(ticket, key) for key in keys}
            if any(v is None for v in values.values()):
                continue
            stmt = select(ItsmIncidentRow).where(
                *(getattr(ItsmIncidentRow, k) == v for k, v in values.items())
            )
            if cutoff is not None:
                stmt = stmt.where(ItsmIncidentRow.opened_at < cutoff)
            rows = list(session.scalars(stmt))
            if len(rows) < min_n and keys:
                continue
            if not rows:
                return None
            hours = [r.resolution_hours for r in rows if r.resolution_hours is not None]
            groups = Counter(r.final_assignment_group for r in rows if r.final_assignment_group)
            codes = Counter(r.closed_code for r in rows if r.closed_code)
            return TicketHistoryStats(
                matched_on={k: str(v) for k, v in values.items()},
                backoff_level=level,
                n_similar=len(rows),
                sla_breach_rate=_rate([not r.made_sla for r in rows if r.made_sla is not None]),
                reopen_rate=_rate([r.reopen_count > 0 for r in rows]),
                mean_reassignments=round(float(np.mean([r.reassignment_count for r in rows])), 3),
                median_resolution_hours=round(float(np.median(hours)), 2) if hours else None,
                p90_resolution_hours=round(float(np.percentile(hours, 90)), 2) if hours else None,
                top_assignment_groups=[g for g, _ in groups.most_common(3)],
                top_closed_codes=[c for c, _ in codes.most_common(3)],
            )
    return None
