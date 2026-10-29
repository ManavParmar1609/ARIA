"""Reads and writes for runs, run events, reports, actions, tool calls and reviewer feedback.

Writes are idempotent upserts keyed by ids ARIA chooses, because graph nodes can be retried and
resumed: running a node twice must not duplicate a report, an action or an audit record.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from aria.contracts.base import utcnow
from aria.contracts.report import IncidentReport, OutboundAction
from aria.contracts.retrieval import ToolCallRecord
from aria.contracts.run import EventKind, RunEvent, RunStatus
from aria.db.engine import session_scope
from aria.db.models import (
    ActionRow,
    FeedbackRow,
    ReportRow,
    RunEventRow,
    RunRow,
    ToolCallRow,
)

_RUN_FIELDS = frozenset(c.name for c in RunRow.__table__.columns) - {"id", "created_at"}


# --- runs ----------------------------------------------------------------------------------------


def create_run(
    engine: Engine,
    run_id: str,
    *,
    request: dict[str, Any],
    trigger: str = "manual",
    title: str | None = None,
    system: str = "generic",
    status: RunStatus = RunStatus.QUEUED,
    **fields: Any,
) -> None:
    """Insert a run, or leave an existing one as it is (safe to call twice)."""
    with session_scope(engine) as session:
        if session.get(RunRow, run_id) is not None:
            return
        extra = {k: v for k, v in fields.items() if k in _RUN_FIELDS}
        session.add(
            RunRow(
                id=run_id,
                status=str(status),
                trigger=trigger,
                title=title,
                system=system,
                request=request,
                **extra,
            )
        )


def update_run(engine: Engine, run_id: str, **fields: Any) -> None:
    unknown = set(fields) - _RUN_FIELDS
    if unknown:
        msg = f"unknown run fields: {', '.join(sorted(unknown))}"
        raise ValueError(msg)
    with session_scope(engine) as session:
        row = session.get(RunRow, run_id)
        if row is None:
            msg = f"unknown run {run_id}"
            raise KeyError(msg)
        for key, value in fields.items():
            setattr(row, key, str(value) if key == "status" else value)
        row.updated_at = utcnow()


def run_dict(row: RunRow) -> dict[str, Any]:
    out = {c.name: getattr(row, c.name) for c in RunRow.__table__.columns}
    for key, value in out.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
    return out


def get_run(engine: Engine, run_id: str) -> dict[str, Any] | None:
    with session_scope(engine) as session:
        row = session.get(RunRow, run_id)
        return run_dict(row) if row is not None else None


def list_runs(
    engine: Engine,
    *,
    limit: int = 50,
    status: str | None = None,
    before: datetime | None = None,
) -> list[dict[str, Any]]:
    with session_scope(engine) as session:
        stmt = select(RunRow).order_by(RunRow.created_at.desc(), RunRow.id.desc())
        if status:
            stmt = stmt.where(RunRow.status == status)
        if before is not None:
            stmt = stmt.where(RunRow.created_at < before)
        return [run_dict(row) for row in session.scalars(stmt.limit(limit))]


def latest_run(engine: Engine, *, trigger: str, system: str) -> dict[str, Any] | None:
    """The newest run with this trigger on this system (the scan's duplicate check)."""
    with session_scope(engine) as session:
        row = session.scalar(
            select(RunRow)
            .where(RunRow.trigger == trigger, RunRow.system == system)
            .order_by(RunRow.created_at.desc(), RunRow.id.desc())
            .limit(1)
        )
        return run_dict(row) if row is not None else None


# --- events --------------------------------------------------------------------------------------


def append_event(
    engine: Engine,
    run_id: str,
    kind: EventKind,
    *,
    node: str | None = None,
    payload: dict[str, Any] | None = None,
) -> RunEvent:
    """Append an event with the next sequence number for the run (unique per run)."""
    for _ in range(5):
        try:
            with session_scope(engine) as session:
                last = session.scalar(
                    select(func.max(RunEventRow.seq)).where(RunEventRow.run_id == run_id)
                )
                seq = 0 if last is None else int(last) + 1
                ts = utcnow()
                session.add(
                    RunEventRow(
                        run_id=run_id, seq=seq, ts=ts, kind=kind, node=node, payload=payload or {}
                    )
                )
            return RunEvent(
                seq=seq, run_id=run_id, ts=ts, kind=kind, node=node, payload=payload or {}
            )
        except IntegrityError:  # another writer took this seq; read the new maximum and retry
            continue
    msg = f"could not append an event to run {run_id}"
    raise RuntimeError(msg)


def list_events(
    engine: Engine, run_id: str, *, after: int = -1, limit: int = 1_000
) -> list[RunEvent]:
    with session_scope(engine) as session:
        rows = session.scalars(
            select(RunEventRow)
            .where(RunEventRow.run_id == run_id, RunEventRow.seq > after)
            .order_by(RunEventRow.seq)
            .limit(limit)
        )
        return [
            RunEvent(
                seq=row.seq,
                run_id=row.run_id,
                ts=row.ts,
                kind=row.kind,  # type: ignore[arg-type]
                node=row.node,
                payload=dict(row.payload),
            )
            for row in rows
        ]


# --- reports and actions -------------------------------------------------------------------------


def save_report(
    engine: Engine,
    report: IncidentReport,
    *,
    markdown: str,
    reviewer: str | None = None,
    comment: str | None = None,
) -> None:
    body = report.model_dump(mode="json")
    with session_scope(engine) as session:
        row = session.get(ReportRow, report.report_id)
        if row is None:
            row = ReportRow(id=report.report_id, run_id=report.run_id, created_at=utcnow())
            session.add(row)
        row.version = report.version
        row.status = report.status
        row.severity = str(report.severity)
        row.title = report.title[:300]
        row.body = body
        row.markdown = markdown
        if reviewer is not None:
            row.reviewer = reviewer
            row.review_comment = comment
            row.reviewed_at = utcnow()


def get_report(engine: Engine, report_id: str) -> tuple[IncidentReport, str] | None:
    with session_scope(engine) as session:
        row = session.get(ReportRow, report_id)
        if row is None:
            return None
        return IncidentReport.model_validate(row.body), row.markdown


def save_actions(
    engine: Engine,
    run_id: str,
    actions: Sequence[OutboundAction],
    *,
    approved_by: str | None = None,
) -> None:
    with session_scope(engine) as session:
        for action in actions:
            row = session.get(ActionRow, action.action_id)
            if row is None:
                row = ActionRow(id=action.action_id, run_id=run_id, created_at=utcnow())
                session.add(row)
            elif row.status == "sent" and action.status != "sent":
                continue  # never let a replay overwrite a delivery that already happened
            row.kind = action.kind
            row.title = action.title[:300]
            row.body = action.body
            row.payload = {
                **action.payload,
                "audience": action.audience,
                "evidence_ids": action.evidence_ids,
            }
            row.status = action.status
            row.result = dict(action.result)
            if approved_by is not None and action.status in ("approved", "sent", "failed"):
                row.approved_by = approved_by
            if action.status == "sent" and row.executed_at is None:
                row.executed_at = utcnow()


def action_statuses(engine: Engine, run_id: str) -> dict[str, str]:
    with session_scope(engine) as session:
        rows = session.execute(
            select(ActionRow.id, ActionRow.status).where(ActionRow.run_id == run_id)
        )
        return {str(row[0]): str(row[1]) for row in rows}


# --- audit and feedback --------------------------------------------------------------------------


def save_tool_calls(engine: Engine, run_id: str, records: Sequence[ToolCallRecord]) -> int:
    added = 0
    with session_scope(engine) as session:
        for record in records:
            if session.get(ToolCallRow, record.call_id) is not None:
                continue
            session.add(
                ToolCallRow(
                    id=record.call_id,
                    run_id=run_id,
                    agent=record.agent,
                    tool=record.tool,
                    arguments=dict(record.arguments),
                    ok=record.ok,
                    summary=record.summary,
                    duration_ms=record.duration_ms,
                )
            )
            added += 1
    return added


def save_feedback(
    engine: Engine,
    run_id: str,
    field: str,
    value: dict[str, Any],
    *,
    author: str,
    comment: str | None = None,
) -> None:
    """Record a reviewer correction once per run, field and author (replays replace it)."""
    with session_scope(engine) as session:
        row = session.scalar(
            select(FeedbackRow).where(
                FeedbackRow.run_id == run_id,
                FeedbackRow.field == field,
                FeedbackRow.author == author,
            )
        )
        if row is None:
            session.add(
                FeedbackRow(run_id=run_id, field=field, value=value, comment=comment, author=author)
            )
        else:
            row.value, row.comment = value, comment


def review_feedback(engine: Engine) -> list[tuple[int, dict[str, Any], bool]]:
    """Every recorded review, oldest first: (id, value, already used for recalibration)."""
    with session_scope(engine) as session:
        rows = session.scalars(
            select(FeedbackRow).where(FeedbackRow.field == "review").order_by(FeedbackRow.id)
        )
        return [(row.id, dict(row.value), row.used_for_training) for row in rows]


def mark_feedback_used(engine: Engine, ids: Sequence[int]) -> None:
    if not ids:
        return
    with session_scope(engine) as session:
        for row in session.scalars(select(FeedbackRow).where(FeedbackRow.id.in_(list(ids)))):
            row.used_for_training = True


# --- the external worker's queue -----------------------------------------------------------------


def claim_runs(
    engine: Engine,
    worker: str,
    *,
    limit: int = 1,
    stale_after_s: float = 600.0,
) -> list[str]:
    """Claim queued runs (and runs whose worker went quiet) for ``worker``, oldest first.

    A claim is a conditional update, so two workers never take the same run.
    """
    now = utcnow()
    stale = now.timestamp() - stale_after_s
    claimed: list[str] = []
    with session_scope(engine) as session:
        candidates = session.scalars(
            select(RunRow)
            .where(RunRow.status.in_([str(RunStatus.QUEUED), str(RunStatus.RUNNING)]))
            .order_by(RunRow.created_at)
            .limit(limit * 5)
        )
        for row in candidates:
            if len(claimed) >= limit:
                break
            free = row.claimed_by is None and row.status == RunStatus.QUEUED
            abandoned = row.claimed_at is not None and row.claimed_at.timestamp() < stale
            if not (free or abandoned):
                continue
            unchanged = (
                RunRow.claimed_at.is_(None)
                if row.claimed_at is None
                else RunRow.claimed_at == row.claimed_at
            )
            result = session.execute(
                update(RunRow)
                .where(RunRow.id == row.id, unchanged)
                .values(claimed_by=worker, claimed_at=now)
            )
            if result.rowcount == 1:  # type: ignore[attr-defined]
                claimed.append(row.id)
    return claimed


def heartbeat(engine: Engine, run_id: str, worker: str) -> None:
    with session_scope(engine) as session:
        session.execute(
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.claimed_by == worker)
            .values(claimed_at=utcnow())
        )


def unfinished_runs(engine: Engine, *, limit: int = 50) -> list[str]:
    """Runs left queued or running by a stopped in-process worker (never claimed)."""
    with session_scope(engine) as session:
        return list(
            session.scalars(
                select(RunRow.id)
                .where(
                    RunRow.status.in_([str(RunStatus.QUEUED), str(RunStatus.RUNNING)]),
                    RunRow.claimed_by.is_(None),
                )
                .order_by(RunRow.created_at)
                .limit(limit)
            )
        )
