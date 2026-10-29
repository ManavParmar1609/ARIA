"""ORM models.

Column lengths are explicit on every indexed string because SQL Server cannot index
NVARCHAR(MAX). JSON columns map to NVARCHAR(MAX) on SQL Server and TEXT on SQLite.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from aria.contracts.base import utcnow
from aria.db.types import UTCDateTime


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSON,
        list[Any]: JSON,
        datetime: UTCDateTime,
    }


# --- datasets ---------------------------------------------------------------------------------


class LogEventRow(Base):
    """One log line from a dataset (Loghub) or an ingested batch."""

    __tablename__ = "log_events"
    __table_args__ = (
        Index("ix_log_events_system_ts", "system", "ts"),
        Index("ix_log_events_window", "window_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(48), index=True)
    system: Mapped[str] = mapped_column(String(48))
    line_no: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime | None]
    node: Mapped[str | None] = mapped_column(String(160))
    component: Mapped[str | None] = mapped_column(String(160))
    level: Mapped[str | None] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(48))
    template_id: Mapped[str | None] = mapped_column(String(64))
    gt_template: Mapped[str | None] = mapped_column(Text)
    window_id: Mapped[str | None] = mapped_column(String(80))


class LogWindowRow(Base):
    """A time window of log events with features and its ground-truth severity label."""

    __tablename__ = "log_windows"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(48), index=True)
    system: Mapped[str] = mapped_column(String(48), index=True)
    start_ts: Mapped[datetime | None]
    end_ts: Mapped[datetime | None]
    n_events: Mapped[int] = mapped_column(Integer)
    alert_tags: Mapped[dict[str, Any]] = mapped_column(default=dict)
    label_severity: Mapped[str | None] = mapped_column(String(8), index=True)
    label_source: Mapped[str] = mapped_column(String(64))
    label_detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    split: Mapped[str] = mapped_column(String(12), index=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class ItsmEventRow(Base):
    """One row of the UCI incident-management event log (an incident state change)."""

    __tablename__ = "itsm_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), index=True)
    incident_state: Mapped[str | None] = mapped_column(String(48))
    active: Mapped[bool | None]
    reassignment_count: Mapped[int | None]
    reopen_count: Mapped[int | None]
    sys_mod_count: Mapped[int | None]
    made_sla: Mapped[bool | None]
    caller_id: Mapped[str | None] = mapped_column(String(64))
    opened_by: Mapped[str | None] = mapped_column(String(64))
    opened_at: Mapped[datetime | None]
    sys_created_by: Mapped[str | None] = mapped_column(String(64))
    sys_created_at: Mapped[datetime | None]
    sys_updated_by: Mapped[str | None] = mapped_column(String(64))
    sys_updated_at: Mapped[datetime | None]
    contact_type: Mapped[str | None] = mapped_column(String(48))
    location: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(64))
    subcategory: Mapped[str | None] = mapped_column(String(64))
    u_symptom: Mapped[str | None] = mapped_column(String(64))
    cmdb_ci: Mapped[str | None] = mapped_column(String(64))
    impact: Mapped[str | None] = mapped_column(String(32))
    urgency: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[str | None] = mapped_column(String(32))
    assignment_group: Mapped[str | None] = mapped_column(String(64))
    assigned_to: Mapped[str | None] = mapped_column(String(64))
    knowledge: Mapped[bool | None]
    u_priority_confirmation: Mapped[bool | None]
    notify: Mapped[str | None] = mapped_column(String(48))
    problem_id: Mapped[str | None] = mapped_column(String(48))
    rfc: Mapped[str | None] = mapped_column(String(48))
    vendor: Mapped[str | None] = mapped_column(String(48))
    caused_by: Mapped[str | None] = mapped_column(String(48))
    closed_code: Mapped[str | None] = mapped_column(String(48))
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]


class ItsmIncidentRow(Base):
    """One incident from the UCI log, aggregated across its events."""

    __tablename__ = "itsm_incidents"
    __table_args__ = (Index("ix_itsm_incidents_match", "cmdb_ci", "category", "subcategory"),)

    number: Mapped[str] = mapped_column(String(32), primary_key=True)
    opened_at: Mapped[datetime | None] = mapped_column(index=True)
    resolved_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    category: Mapped[str | None] = mapped_column(String(64))
    subcategory: Mapped[str | None] = mapped_column(String(64))
    symptom: Mapped[str | None] = mapped_column(String(64))
    cmdb_ci: Mapped[str | None] = mapped_column(String(64))
    contact_type: Mapped[str | None] = mapped_column(String(48))
    location: Mapped[str | None] = mapped_column(String(64))
    first_assignment_group: Mapped[str | None] = mapped_column(String(64))
    final_assignment_group: Mapped[str | None] = mapped_column(String(64))
    impact: Mapped[str | None] = mapped_column(String(32))
    urgency: Mapped[str | None] = mapped_column(String(32))
    priority_at_open: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[str | None] = mapped_column(String(32), index=True)
    knowledge: Mapped[bool | None]
    priority_confirmation: Mapped[bool | None]
    made_sla: Mapped[bool | None]
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    reassignment_count: Mapped[int] = mapped_column(Integer, default=0)
    sys_mod_count: Mapped[int] = mapped_column(Integer, default=0)
    closed_code: Mapped[str | None] = mapped_column(String(48))
    resolution_hours: Mapped[float | None] = mapped_column(Float)
    n_events: Mapped[int] = mapped_column(Integer)
    split: Mapped[str] = mapped_column(String(12), index=True)


# --- knowledge --------------------------------------------------------------------------------


class IncidentRow(Base):
    """Incident memory: past incidents ARIA can retrieve, with how they were fixed."""

    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    system: Mapped[str] = mapped_column(String(48), index=True)
    components: Mapped[list[Any]] = mapped_column(default=list)
    failure_mode: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(8))
    summary: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[str] = mapped_column(Text)
    runbook_slug: Mapped[str | None] = mapped_column(String(96))
    first_seen: Mapped[datetime | None]
    last_seen: Mapped[datetime | None]
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    affected_nodes: Mapped[int] = mapped_column(Integer, default=0)
    mttr_minutes: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    report_id: Mapped[str | None] = mapped_column(String(64))
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class RunbookRow(Base):
    __tablename__ = "runbooks"

    slug: Mapped[str] = mapped_column(String(96), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    systems: Mapped[list[Any]] = mapped_column(default=list)
    failure_modes: Mapped[list[Any]] = mapped_column(default=list)
    risk: Mapped[str] = mapped_column(String(16), default="low")
    steps: Mapped[list[Any]] = mapped_column(default=list)
    body: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


# --- runs -------------------------------------------------------------------------------------


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    status: Mapped[str] = mapped_column(String(24))
    trigger: Mapped[str] = mapped_column(String(24), default="manual")
    title: Mapped[str | None] = mapped_column(String(300))
    system: Mapped[str] = mapped_column(String(48), default="generic")
    request: Mapped[dict[str, Any]] = mapped_column(default=dict)
    severity: Mapped[str | None] = mapped_column(String(8))
    decided_by: Mapped[str | None] = mapped_column(String(16))
    auditable: Mapped[bool | None]
    confidence: Mapped[float | None] = mapped_column(Float)
    providers: Mapped[list[Any]] = mapped_column(default=list)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    report_id: Mapped[str | None] = mapped_column(String(64))
    parent_run_id: Mapped[str | None] = mapped_column(String(64))
    forked_from_checkpoint: Mapped[str | None] = mapped_column(String(64))
    alert_group_id: Mapped[str | None] = mapped_column(String(64))
    claimed_by: Mapped[str | None] = mapped_column(String(64))
    claimed_at: Mapped[datetime | None]


class RunEventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(default=utcnow)
    kind: Mapped[str] = mapped_column(String(24))
    node: Mapped[str | None] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ReportRow(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[dict[str, Any]] = mapped_column(default=dict)
    markdown: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str | None] = mapped_column(String(120))
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ActionRow(Base):
    """Outbound actions ARIA proposed; each is sent only after a reviewer approves it."""

    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    executed_at: Mapped[datetime | None]
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ToolCallRow(Base):
    """Audit log of every MCP tool call an agent made."""

    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    agent: Mapped[str] = mapped_column(String(48))
    tool: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ok: Mapped[bool] = mapped_column(Boolean)
    summary: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(default=utcnow)


class FeedbackRow(Base):
    """Reviewer corrections, queued for recalibration (active learning)."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    field: Mapped[str] = mapped_column(String(32))
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    comment: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(120))
    used_for_training: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AlertRow(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_fingerprint_status", "fingerprint", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))
    labels: Mapped[dict[str, Any]] = mapped_column(default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(default=dict)
    starts_at: Mapped[datetime | None]
    ends_at: Mapped[datetime | None]
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
    group_id: Mapped[str | None] = mapped_column(String(64), index=True)


class AlertGroupRow(Base):
    """Correlated alerts that ARIA triages as one incident."""

    __tablename__ = "alert_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(256), index=True)
    system: Mapped[str] = mapped_column(String(48), default="generic")
    status: Mapped[str] = mapped_column(String(16), default="open")
    alert_count: Mapped[int] = mapped_column(Integer, default=0)
    first_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_at: Mapped[datetime] = mapped_column(default=utcnow)
    run_id: Mapped[str | None] = mapped_column(String(64))


class EvalRunRow(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    suite: Mapped[str] = mapped_column(String(32))
    git_sha: Mapped[str | None] = mapped_column(String(48))
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)


# --- LangGraph checkpoints --------------------------------------------------------------------


class CheckpointRow(Base):
    __tablename__ = "lg_checkpoints"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(255), primary_key=True, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(64))
    type: Mapped[str | None] = mapped_column(String(32))
    checkpoint: Mapped[bytes] = mapped_column(LargeBinary)
    metadata_type: Mapped[str | None] = mapped_column(String(32))
    checkpoint_metadata: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class CheckpointWriteRow(Base):
    __tablename__ = "lg_writes"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(255), primary_key=True, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(String(32))
    value: Mapped[bytes] = mapped_column(LargeBinary)
    task_path: Mapped[str] = mapped_column(String(255), default="")
