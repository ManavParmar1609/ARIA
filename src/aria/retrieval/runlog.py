"""A run's analysed log lines, stored so read-only tools (and the MCP server) can query them.

Lines go into ``log_events`` with ``dataset="run"`` and ``window_id=<run id>``. They are already
redacted, and quarantined lines are never stored, so tools cannot hand an injected instruction
back to a model.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine

from aria.db.engine import session_scope
from aria.db.models import LogEventRow
from aria.parsing.features import ERROR_LEVELS
from aria.parsing.parser import ParsedLine
from aria.parsing.signals import WARN

RUN_DATASET = "run"
_LIKE_ESCAPE = re.compile(r"([%_\\])")


def store_run_lines(engine: Engine, run_id: str, system: str, lines: Sequence[ParsedLine]) -> int:
    rows = [
        {
            "dataset": RUN_DATASET,
            "system": system,
            "line_no": line.idx + 1,
            "ts": line.record.ts,
            "node": line.record.node,
            "component": line.record.component,
            "level": line.record.level,
            "message": line.record.message[:2_000],
            "template_id": line.template_id,
            "window_id": run_id,
        }
        for line in lines
    ]
    with session_scope(engine) as session:
        session.execute(
            delete(LogEventRow).where(
                LogEventRow.window_id == run_id, LogEventRow.dataset == RUN_DATASET
            )
        )
        for start in range(0, len(rows), 5_000):
            session.execute(insert(LogEventRow), rows[start : start + 5_000])
    return len(rows)


def copy_run_lines(engine: Engine, source_run: str, target_run: str) -> int:
    """Give a forked run its own copy of the source run's lines, so its tools stay run-scoped."""
    columns = ("system", "line_no", "ts", "node", "component", "level", "message", "template_id")
    with session_scope(engine) as session:
        rows = [
            {
                **{c: getattr(row, c) for c in columns},
                "dataset": RUN_DATASET,
                "window_id": target_run,
            }
            for row in session.scalars(
                select(LogEventRow).where(
                    LogEventRow.window_id == source_run, LogEventRow.dataset == RUN_DATASET
                )
            )
        ]
        session.execute(
            delete(LogEventRow).where(
                LogEventRow.window_id == target_run, LogEventRow.dataset == RUN_DATASET
            )
        )
        for start in range(0, len(rows), 5_000):
            session.execute(insert(LogEventRow), rows[start : start + 5_000])
    return len(rows)


def _like(term: str) -> str:
    """A LIKE pattern matching ``term`` literally (``%``, ``_`` and ``\\`` are escaped)."""
    return "%" + _LIKE_ESCAPE.sub(lambda m: "\\" + m.group(1), term) + "%"


def _row(event: LogEventRow) -> dict[str, Any]:
    return {
        "line_no": event.line_no,
        "ts": event.ts.isoformat() if event.ts else None,
        "node": event.node,
        "component": event.component,
        "level": event.level,
        "message": event.message,
        "template_id": event.template_id,
    }


def search_lines(
    engine: Engine,
    terms: Sequence[str],
    *,
    run_id: str | None = None,
    system: str | None = None,
    limit: int = 20,
    errors_only: bool = False,
    datasets_only: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """Lines containing every term (case-insensitive); returns (lines, truncated).

    ``datasets_only`` leaves runs' own lines out of a search by system."""
    stmt = select(LogEventRow)
    if run_id is not None:
        stmt = stmt.where(LogEventRow.window_id == run_id, LogEventRow.dataset == RUN_DATASET)
    elif datasets_only:
        stmt = stmt.where(LogEventRow.dataset != RUN_DATASET)
    if system is not None:
        stmt = stmt.where(LogEventRow.system == system)
    for term in [t for t in terms if t][:6]:
        stmt = stmt.where(LogEventRow.message.ilike(_like(term), escape="\\"))
    if errors_only:
        stmt = stmt.where(LogEventRow.level.in_(sorted(ERROR_LEVELS)))
    stmt = stmt.order_by(LogEventRow.line_no).limit(limit + 1)
    with session_scope(engine) as session:
        rows = [_row(e) for e in session.scalars(stmt)]
    return rows[:limit], len(rows) > limit


def template_examples(
    engine: Engine, run_id: str, template_id: str, *, limit: int = 5
) -> list[dict[str, Any]]:
    stmt = (
        select(LogEventRow)
        .where(LogEventRow.window_id == run_id, LogEventRow.dataset == RUN_DATASET)
        .where(LogEventRow.template_id == template_id)
        .order_by(LogEventRow.line_no)
        .limit(limit)
    )
    with session_scope(engine) as session:
        return [_row(e) for e in session.scalars(stmt)]


def _run_events(engine: Engine, run_id: str, component: str | None = None) -> list[LogEventRow]:
    stmt = select(LogEventRow).where(
        LogEventRow.window_id == run_id, LogEventRow.dataset == RUN_DATASET
    )
    if component is not None:
        stmt = stmt.where(LogEventRow.component == component)
    with session_scope(engine) as session:
        events = list(session.scalars(stmt))
        session.expunge_all()
    return events


def component_timeline(engine: Engine, run_id: str, component: str) -> list[dict[str, Any]]:
    """Per-minute totals, errors and warnings for one component, from its first line onward."""
    stamped = [(e.ts, e.level) for e in _run_events(engine, run_id, component) if e.ts is not None]
    if not stamped:
        return []
    start = min(ts for ts, _ in stamped)
    buckets: dict[int, Counter[str]] = defaultdict(Counter)
    for ts, level in stamped:
        minute = int((ts - start).total_seconds() // 60)
        buckets[minute]["total"] += 1
        if level in ERROR_LEVELS:
            buckets[minute]["errors"] += 1
        elif level == WARN:
            buckets[minute]["warnings"] += 1
    return [
        {"minute": m, "total": c["total"], "errors": c["errors"], "warnings": c["warnings"]}
        for m, c in sorted(buckets.items())
    ]


def node_breakdown(
    engine: Engine, run_id: str, component: str | None = None, *, limit: int = 20
) -> list[dict[str, Any]]:
    totals: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    for event in _run_events(engine, run_id, component):
        node = event.node or "(unknown)"
        totals[node] += 1
        if event.level in ERROR_LEVELS:
            errors[node] += 1
        elif event.level == WARN:
            warnings[node] += 1
    ranked = sorted(totals, key=lambda n: (-errors[n], -warnings[n], -totals[n], n))[:limit]
    return [
        {"node": n, "errors": errors[n], "warnings": warnings[n], "total": totals[n]}
        for n in ranked
    ]
