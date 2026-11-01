"""Retention: purge runs past the configured period, with everything that belongs only to them.

Off by default. With ``retention.days`` at 0, nothing is ever deleted unless someone deletes a run
by hand (``DELETE /api/v1/runs/{id}``). With a period set, a run is purged once nothing has
happened to it for the whole period:

* its last change (``runs.updated_at``: it was created, paused for review, was reviewed, or had a
  message sent again) is older than the cutoff;
* no one has reviewed it or rated it blind since the cutoff;
* it is not queued or running, and no process holds it right then. A run that is held is left
  for the next purge.

Each run goes in a transaction of its own (``purge_run``). What a run owns is written down once,
in ``owned``, for the purge and for deleting one run by hand. Rows go children first, so every
foreign key holds whether or not the database cascades.
Runbooks, the incidents memory was seeded with, the routine log templates ARIA learned from many
runs, datasets, evaluation runs and other runs (copies of a purged run included) are never
touched.
"""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from aria.contracts.base import utcnow
from aria.contracts.run import RunStatus
from aria.db.engine import session_scope
from aria.db.models import (
    STORE_SEP,
    ActionRow,
    AlertGroupRow,
    AlertRow,
    CheckpointBlobRow,
    CheckpointRow,
    CheckpointWriteRow,
    FeedbackRow,
    IncidentRow,
    LogEventRow,
    ReportRow,
    RunEventRow,
    RunRow,
    StoreItemRow,
    ToolCallRow,
)
from aria.db.repository import CLAIM_STALE_S
from aria.retrieval.memory import run_incident_id
from aria.retrieval.runlog import RUN_DATASET

# Runs a purge reads, or a dry run counts, at once: few enough that every list of ids it sends
# stays well inside SQL Server's 2,100 parameters to a statement. It deletes them one by one.
BATCH = 200
# What a purge leaves in place of the newest feedback row when that row was a purged run's.
RETIRED = "retired"
ACTIVE = (str(RunStatus.QUEUED), str(RunStatus.RUNNING))
# The reviewer corrections the severity step reads back, one per run, keyed by the run's id.
CORRECTIONS = f"feedback{STORE_SEP}"


def purge_owner() -> str:
    """The name a purge holds runs under while it deletes them, unique to this purge, so it never
    passes for a process that is driving one. It fits the claim column (64 characters)."""
    return f"purge:{socket.gethostname()[:32]}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


def owned(run_ids: Sequence[str]) -> list[tuple[str, Any, ColumnElement[bool]]]:
    """What these runs own, as (what it is, its table, which rows), children before parents.

    That is each run's checkpoints, its reviewer correction in learned memory, its stored log
    lines, its tool-call audit, its reviews and blind checks, the incident memory entry it became
    once published, the alert group that opened it with that group's alerts, its events, its
    report, its messages and the run itself.
    """
    ids = list(run_ids)
    groups = select(AlertGroupRow.id).where(AlertGroupRow.run_id.in_(ids))
    return [
        ("checkpoint writes", CheckpointWriteRow, CheckpointWriteRow.thread_id.in_(ids)),
        ("checkpoint values", CheckpointBlobRow, CheckpointBlobRow.thread_id.in_(ids)),
        ("checkpoints", CheckpointRow, CheckpointRow.thread_id.in_(ids)),
        (
            "reviewer corrections",
            StoreItemRow,
            and_(StoreItemRow.namespace.startswith(CORRECTIONS), StoreItemRow.key.in_(ids)),
        ),
        (
            "log lines",
            LogEventRow,
            and_(LogEventRow.dataset == RUN_DATASET, LogEventRow.window_id.in_(ids)),
        ),
        ("tool calls", ToolCallRow, ToolCallRow.run_id.in_(ids)),
        ("reviews and blind checks", FeedbackRow, FeedbackRow.run_id.in_(ids)),
        (
            "incident memory",
            IncidentRow,
            and_(
                IncidentRow.id.in_([run_incident_id(run_id) for run_id in ids]),
                IncidentRow.source == "run",
            ),
        ),
        ("alerts", AlertRow, AlertRow.group_id.in_(groups)),
        ("alert groups", AlertGroupRow, AlertGroupRow.run_id.in_(ids)),
        ("events", RunEventRow, RunEventRow.run_id.in_(ids)),
        ("reports", ReportRow, ReportRow.run_id.in_(ids)),
        ("messages", ActionRow, ActionRow.run_id.in_(ids)),
        ("runs", RunRow, RunRow.id.in_(ids)),
    ]


def count_owned(session: Session, run_ids: Sequence[str]) -> dict[str, int]:
    """How many rows of each kind deleting these runs would remove."""
    counts: dict[str, int] = {}
    for kind, table, rows in owned(run_ids):
        counts[kind] = int(session.scalar(select(func.count()).select_from(table).where(rows)) or 0)
    return counts


def delete_owned(session: Session, run_ids: Sequence[str]) -> dict[str, int]:
    """Delete these runs and everything they own (``owned``), in the caller's transaction.

    Returns how many rows of each kind went. The caller holds the runs (a claim), so no process
    is driving them meanwhile.
    """
    counts: dict[str, int] = {}
    for kind, table, rows in owned(run_ids):
        if table is FeedbackRow:
            counts[kind] = _delete_feedback(session, rows)
        else:
            counts[kind] = _run(session, delete(table).where(rows))
    return counts


def _delete_feedback(session: Session, rows: ColumnElement[bool]) -> int:
    """Delete the runs' reviews and blind checks, but keep the table's highest id taken.

    SQLite hands the highest id out again once its row is gone, and recalibration skips blind
    checks by id (it remembers the highest it applied), so a new check given a reused id would
    never be learned from. When the newest row is one of these runs', it stays as an empty
    placeholder: no run, no reviewer, no ratings. Placeholders that newer rows have passed go.
    """
    top = session.scalar(select(func.max(FeedbackRow.id)))
    gone = _run(session, delete(FeedbackRow).where(rows, FeedbackRow.id != top))
    emptied = _run(
        session,
        update(FeedbackRow)
        .where(rows, FeedbackRow.id == top)
        .values(
            run_id="",
            field=RETIRED,
            value={},
            comment=None,
            author="aria:retention",
            used_for_training=True,
        ),
    )
    _run(session, delete(FeedbackRow).where(FeedbackRow.field == RETIRED, FeedbackRow.id != top))
    return gone + emptied


def _run(session: Session, statement: Any) -> int:
    """Run a bulk delete or update and say how many rows it changed. Nothing in the session
    mirrors these rows, so it is not asked to keep them in step."""
    result = session.execute(statement.execution_options(synchronize_session=False))
    return max(0, int(getattr(result, "rowcount", 0) or 0))


def _expired(cutoff: datetime) -> ColumnElement[bool]:
    """Runs nothing has happened to since ``cutoff`` that are not queued or running."""
    reviewed_since = (
        select(FeedbackRow.id)
        .where(FeedbackRow.run_id == RunRow.id, FeedbackRow.created_at >= cutoff)
        .exists()
    )
    return and_(RunRow.updated_at < cutoff, RunRow.status.not_in(ACTIVE), ~reviewed_since)


def _free(now: datetime) -> ColumnElement[bool]:
    """Runs no process holds: never claimed, let go, or held by one that stopped renewing."""
    stale = now - timedelta(seconds=CLAIM_STALE_S)
    return or_(RunRow.claimed_by.is_(None), RunRow.claimed_at.is_(None), RunRow.claimed_at < stale)


def expired_runs(
    engine: Engine,
    cutoff: datetime,
    *,
    limit: int = BATCH,
    after: tuple[datetime, str] | None = None,
) -> list[tuple[datetime, str]]:
    """The next ``limit`` runs past ``cutoff``, oldest change first, as (last change, run id),
    starting after the run ``after`` (the last one of the previous page)."""
    page = select(RunRow.updated_at, RunRow.id).where(_expired(cutoff))
    if after is not None:
        moment, run_id = after
        page = page.where(
            or_(
                RunRow.updated_at > moment,
                and_(RunRow.updated_at == moment, RunRow.id > run_id),
            )
        )
    with session_scope(engine) as session:
        rows = session.execute(page.order_by(RunRow.updated_at, RunRow.id).limit(limit))
        return [(moment, str(run_id)) for moment, run_id in rows]


def purge_run(engine: Engine, run_id: str, cutoff: datetime, owner: str) -> dict[str, int] | None:
    """Take the run if it is still past ``cutoff`` and free, and delete it with everything it
    owns, in one transaction: either all of it goes or none of it does.

    Returns how many rows of each kind went, or None when the run was not taken (a process holds
    it, or something happened to it meanwhile). A review or a drive that comes for it meanwhile
    waits for the transaction, then finds no run. One run at a time keeps each transaction as
    short as deleting one run by hand, so a purge never holds a SQLite database for long.
    """
    now = utcnow()
    with session_scope(engine) as session:
        taken = _run(
            session,
            update(RunRow)
            .where(RunRow.id == run_id, _expired(cutoff), _free(now))
            .values(claimed_by=owner, claimed_at=now),
        )
        return delete_owned(session, [run_id]) if taken == 1 else None


@dataclass
class PurgeResult:
    """What a purge deleted, or in a dry run would delete."""

    days: int
    cutoff: datetime
    dry_run: bool
    runs: list[str] = field(default_factory=list)
    # Rows of each kind (``owned``), the runs themselves included.
    rows: dict[str, int] = field(default_factory=dict)
    # Runs past the period that a process held at that moment: the next purge takes them.
    busy: list[str] = field(default_factory=list)

    def add(self, counts: dict[str, int]) -> None:
        for kind, count in counts.items():
            self.rows[kind] = self.rows.get(kind, 0) + count


def purge(
    engine: Engine,
    *,
    days: int,
    owner: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    batch: int = BATCH,
) -> PurgeResult:
    """Delete every run nothing has happened to for ``days`` days, with what it owns.

    A dry run deletes nothing and holds nothing: it counts what a purge would delete now.
    """
    if days <= 0:
        msg = "retention is off: a purge needs a period of at least one day"
        raise ValueError(msg)
    cutoff = (now or utcnow()) - timedelta(days=days)
    result = PurgeResult(days=days, cutoff=cutoff, dry_run=dry_run)
    owner = owner or purge_owner()
    after: tuple[datetime, str] | None = None
    while page := expired_runs(engine, cutoff, limit=batch, after=after):
        after = page[-1]
        ids = [run_id for _, run_id in page]
        if dry_run:
            with session_scope(engine) as session:
                result.add(count_owned(session, ids))
            result.runs.extend(ids)
            continue
        for run_id in ids:
            counts = purge_run(engine, run_id, cutoff, owner)
            if counts is None:
                result.busy.append(run_id)
            else:
                result.add(counts)
                result.runs.append(run_id)
    return result
