"""Retention: off by default, and a purge that deletes old runs with exactly what they own.

Every test runs on a fresh SQLite database, with runs triaged offline through the real graph.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from typer.testing import CliRunner

from aria.api.jobs import start_background_jobs
from aria.cli import app
from aria.config import AppConfig, RetentionConfig, load_app_config, reset_caches
from aria.contracts.base import utcnow
from aria.contracts.inputs import TriageRequest
from aria.contracts.run import RunStatus
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db, session_scope
from aria.db.models import (
    STORE_SEP,
    ActionRow,
    AlertGroupRow,
    AlertRow,
    CheckpointRow,
    FeedbackRow,
    IncidentRow,
    LogEventRow,
    ReportRow,
    RunbookRow,
    RunEventRow,
    RunRow,
    StoreItemRow,
    ToolCallRow,
)
from aria.graph import retention
from aria.graph.runner import TriageRunner
from aria.retrieval.memory import IncidentMemory, run_incident_id
from aria.retrieval.runbooks import load_runbooks, sync_runbooks
from aria.retrieval.runlog import RUN_DATASET
from aria.retrieval.seed import incident_from_scenario
from aria.services import Services

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
OLD = timedelta(days=40)


@dataclass
class Env:
    runner: TriageRunner
    services: Services
    builder: ScenarioBuilder

    @property
    def engine(self) -> Any:
        return self.services.engine


@pytest.fixture
async def env() -> AsyncIterator[Env]:
    engine = get_engine()
    init_db(engine)
    builder = ScenarioBuilder(LinePools.from_loghub(FIXTURES))
    runbooks = load_runbooks(Path("runbooks"))
    sync_runbooks(engine, runbooks)
    seeded = builder.build("hdfs.block_serve_exceptions", seed=7, nodes=3, duration_min=5)
    await IncidentMemory(engine, None).bulk_insert([incident_from_scenario(seeded, runbooks)])
    services = await Services.create()
    yield Env(TriageRunner(services), services, builder)
    await services.aclose()


def kernel_panic(env: Env, seed: int) -> TriageRequest:
    scenario = env.builder.build(
        "bgl.kernel_panic", seed=seed, nodes=4, duration_min=6, incident_per_min=8
    )
    return TriageRequest(title="Kernel panics", system="bgl", logs=scenario.lines, synthetic=True)


async def published(env: Env, seed: int) -> str:
    """A run triaged, then edited to another level and approved: it owns one of everything."""
    outcome = await env.runner.start(kernel_panic(env, seed))
    assert outcome.interrupt is not None
    other = "SEV4" if outcome.interrupt["severity"] != "SEV4" else "SEV3"
    done = await env.runner.resume(
        outcome.run_id,
        {"decision": "edit", "reviewer": "ana", "edits": {"severity": other}},
    )
    assert done.status is RunStatus.PUBLISHED
    return outcome.run_id


def opened_by_alerts(env: Env, run_id: str, alerts: int = 2) -> str:
    """Give the run the alert group that opened it, with its alerts."""
    group = f"grp-{run_id[-10:]}"
    with session_scope(env.engine) as session:
        session.add(AlertGroupRow(id=group, key=f"k-{run_id}", status="closed", run_id=run_id))
        for n in range(alerts):
            session.add(
                AlertRow(
                    fingerprint=f"f{n}",
                    source="alertmanager",
                    name="Disk",
                    status="firing",
                    group_id=group,
                )
            )
    return group


def age(env: Env, run_id: str, by: timedelta = OLD) -> None:
    """Make it look as if nothing has happened to the run for ``by``."""
    then = utcnow() - by
    with session_scope(env.engine) as session:
        session.execute(update(RunRow).where(RunRow.id == run_id).values(updated_at=then))
        session.execute(update(RunEventRow).where(RunEventRow.run_id == run_id).values(ts=then))
        session.execute(
            update(FeedbackRow).where(FeedbackRow.run_id == run_id).values(created_at=then)
        )


def held(env: Env, run_id: str) -> int:
    """Rows anywhere that belong to the run."""
    corrections = StoreItemRow.namespace.startswith(f"feedback{STORE_SEP}")
    with session_scope(env.engine) as session:
        counted = [
            session.scalar(select(func.count()).select_from(table).where(rows))
            for table, rows in (
                (RunRow, RunRow.id == run_id),
                (RunEventRow, RunEventRow.run_id == run_id),
                (ReportRow, ReportRow.run_id == run_id),
                (ActionRow, ActionRow.run_id == run_id),
                (CheckpointRow, CheckpointRow.thread_id == run_id),
                (ToolCallRow, ToolCallRow.run_id == run_id),
                (FeedbackRow, FeedbackRow.run_id == run_id),
                (
                    LogEventRow,
                    (LogEventRow.window_id == run_id) & (LogEventRow.dataset == RUN_DATASET),
                ),
                (IncidentRow, IncidentRow.id == run_incident_id(run_id)),
                (StoreItemRow, corrections & (StoreItemRow.key == run_id)),
                (AlertGroupRow, AlertGroupRow.run_id == run_id),
            )
        ]
    return sum(int(n or 0) for n in counted)


def shared(env: Env) -> tuple[int, int, int]:
    """What no purge may touch: runbooks, the incidents memory was seeded with, and the routine
    templates ARIA learned from every run."""
    with session_scope(env.engine) as session:
        runbooks = session.scalar(select(func.count()).select_from(RunbookRow))
        curated = session.scalar(
            select(func.count()).select_from(IncidentRow).where(IncidentRow.source != "run")
        )
        templates = session.scalar(
            select(func.count())
            .select_from(StoreItemRow)
            .where(StoreItemRow.namespace.startswith(f"templates{STORE_SEP}"))
        )
    return int(runbooks or 0), int(curated or 0), int(templates or 0)


# --- configuration --------------------------------------------------------------------------------


def test_retention_is_off_unless_an_operator_sets_a_period() -> None:
    assert RetentionConfig().days == 0
    assert load_app_config(Path("config/aria.yaml")).retention == RetentionConfig()
    with pytest.raises(ValueError, match="at least one day"):
        retention.purge(get_engine(), days=0)


def test_a_purge_runs_at_most_once_a_minute() -> None:
    assert RetentionConfig(days=30, purge_interval_s=3_600).purge_interval_s == 3_600
    with pytest.raises(ValidationError, match="once a minute"):
        RetentionConfig(days=30, purge_interval_s=5)


def test_the_period_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARIA_RETENTION_DAYS", "90")
    monkeypatch.setenv("ARIA_PURGE_INTERVAL_S", "3600")
    config: AppConfig = load_app_config(Path("config/aria.yaml"))
    assert (config.retention.days, config.retention.purge_interval_s) == (90, 3_600)


# --- the purge ------------------------------------------------------------------------------------


async def test_a_purge_deletes_old_runs_with_what_they_own_and_nothing_else(env: Env) -> None:
    old, recent = await published(env, seed=8), await published(env, seed=9)
    opened_by_alerts(env, old)
    opened_by_alerts(env, recent)
    age(env, old)
    waiting = (await env.runner.start(kernel_panic(env, seed=10))).run_id
    age(env, waiting)  # paused for review long ago, and never reviewed
    assert held(env, old)
    kept = held(env, recent)
    before = shared(env)

    result = retention.purge(env.engine, days=30)

    assert sorted(result.runs) == sorted([old, waiting])
    assert not result.busy
    assert held(env, old) == held(env, waiting) == 0
    assert result.rows["runs"] == 2
    for kind in ("events", "reports", "messages", "checkpoints", "log lines", "tool calls"):
        assert result.rows[kind] > 0, kind
    assert result.rows["reviews and blind checks"] == 1
    assert result.rows["reviewer corrections"] == 1
    assert result.rows["incident memory"] == 1
    assert (result.rows["alert groups"], result.rows["alerts"]) == (1, 2)
    with session_scope(env.engine) as session:
        orphans = select(AlertRow.id).where(AlertRow.group_id.not_in(select(AlertGroupRow.id)))
        assert not session.scalars(orphans).first()  # no alert outlives its group
        assert not session.execute(text("PRAGMA foreign_key_check")).all()
    assert held(env, recent) == kept  # the recent run keeps everything
    assert repo.get_report(env.engine, f"rpt-{recent}") is not None
    assert shared(env) == before


async def test_a_dry_run_counts_what_a_purge_then_deletes(env: Env) -> None:
    old = await published(env, seed=8)
    opened_by_alerts(env, old)
    age(env, old)
    rows = held(env, old)

    counted = retention.purge(env.engine, days=30, dry_run=True)
    assert counted.dry_run
    assert counted.runs == [old]
    assert held(env, old) == rows  # nothing was deleted, or held
    assert repo.get_run(env.engine, old)["claimed_by"] is None  # type: ignore[index]

    deleted = retention.purge(env.engine, days=30)
    assert deleted.rows == counted.rows
    assert held(env, old) == 0


async def test_runs_at_work_held_or_touched_within_the_period_are_kept(env: Env) -> None:
    engine = env.engine
    queued = env.runner.submit(kernel_panic(env, seed=8))
    age(env, queued)
    busy = await published(env, seed=9)
    age(env, busy)
    assert repo.claim_run(engine, busy, "another-process", status=None)  # it is working on it
    age(env, busy)
    rated = await published(env, seed=10)
    age(env, rated)
    repo.save_feedback(engine, rated, "blind_check", {"to": "SEV2"}, author="raj")  # rated today
    recent = await published(env, seed=11)
    age(env, recent, timedelta(days=29))
    logged = (await env.runner.start(kernel_panic(env, seed=12))).run_id
    age(env, logged)
    repo.append_event(engine, logged, "guardrail", node="scan", payload={"quarantined": 1})

    result = retention.purge(engine, days=30)

    assert result.runs == []
    assert result.busy == [busy]
    for run_id in (queued, busy, rated, recent, logged):
        assert repo.get_run(engine, run_id) is not None
    repo.release_run(engine, busy, "another-process")
    age(env, busy)
    assert retention.purge(engine, days=30).runs == [busy]  # the next purge takes it


async def test_purging_the_newest_review_never_hands_its_id_out_again(env: Env) -> None:
    """Recalibration skips blind checks by id, and SQLite reuses a deleted highest id."""
    engine = env.engine
    old = await published(env, seed=8)
    repo.save_feedback(engine, old, "blind_check", {"to": "SEV2"}, author="raj")
    age(env, old)
    with session_scope(engine) as session:
        newest = int(session.scalar(select(func.max(FeedbackRow.id))) or 0)

    retention.purge(engine, days=30)

    assert not repo.feedback_of(engine, "blind_check")
    assert not repo.feedback_of(engine, "review")
    assert repo.list_feedback(engine) == []
    with session_scope(engine) as session:
        kept = session.get(FeedbackRow, newest)
        assert kept is not None  # an empty placeholder holds the id
        assert (kept.run_id, kept.value, kept.author) == ("", {}, "aria:retention")
    later = await published(env, seed=9)
    repo.save_feedback(engine, later, "blind_check", {"to": "SEV3"}, author="raj")
    ids = [feedback_id for feedback_id, _, _ in repo.feedback_of(engine, "blind_check")]
    assert ids
    assert min(ids) > newest
    age(env, later)
    retention.purge(engine, days=30)
    with session_scope(engine) as session:
        assert session.get(FeedbackRow, newest) is None  # passed by newer rows, it goes


async def test_deleting_a_run_by_hand_removes_what_a_purge_would(env: Env) -> None:
    run_id = await published(env, seed=8)
    opened_by_alerts(env, run_id)
    await env.runner.delete(run_id)
    assert held(env, run_id) == 0


# --- the command and the job ----------------------------------------------------------------------


def said(output: str) -> str:
    """The command's output as one line: rich wraps long lines to the terminal."""
    return " ".join(output.split())


async def test_the_purge_command_counts_first_and_does_nothing_while_retention_is_off(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = await published(env, seed=8)
    age(env, old)
    cli = CliRunner()

    off = cli.invoke(app, ["purge"])
    assert off.exit_code == 0, off.output
    assert "Retention is off, so nothing was deleted" in said(off.output)
    assert repo.get_run(env.engine, old) is not None

    dry = cli.invoke(app, ["purge", "--days", "30", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert ": 1 would be deleted." in said(dry.output)
    assert repo.get_run(env.engine, old) is not None

    monkeypatch.setenv("ARIA_RETENTION_DAYS", "30")
    reset_caches()
    done = cli.invoke(app, ["purge"])
    assert done.exit_code == 0, done.output
    assert ": 1 deleted." in said(done.output)
    assert repo.get_run(env.engine, old) is None


async def test_the_worker_purges_on_a_schedule_only_when_asked(env: Env) -> None:
    env.services.config.severity.recalibrate_check_s = 0  # only the purge, if anything
    assert start_background_jobs(env.services, env.runner, asyncio.Event()) == []
    env.services.config.retention = RetentionConfig(days=30)  # a period, but no schedule
    assert start_background_jobs(env.services, env.runner, asyncio.Event()) == []

    old = await published(env, seed=8)
    age(env, old)
    env.services.config.retention = RetentionConfig(days=30, purge_interval_s=60)
    stop = asyncio.Event()
    tasks = start_background_jobs(env.services, env.runner, stop)
    assert [t.get_name() for t in tasks] == ["aria-purge"]
    purging = tasks[0]
    for _ in range(200):
        if repo.get_run(env.engine, old) is None:
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert purging.done()
    assert repo.get_run(env.engine, old) is None
    assert env.services.memory.get(run_incident_id(old)) is None  # memory let it go at once
