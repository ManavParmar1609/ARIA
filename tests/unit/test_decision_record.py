"""The decision record: an append-only, hash-chained log of every decision ARIA or a person took.

Every test runs on a fresh SQLite database; runs go through the real graph, offline.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import respx
from asgi_lifespan import LifespanManager
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from typer.testing import CliRunner

from aria.api.app import create_app
from aria.cli import app
from aria.config import reset_caches
from aria.contracts.base import Severity
from aria.contracts.inputs import RunOptions, TriageRequest
from aria.contracts.record import GENESIS, DecisionRecord
from aria.contracts.run import RunStatus
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db import migrate, record
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db, session_scope
from aria.db.models import DecisionRecordRow
from aria.graph import workflow
from aria.graph.runner import TriageRunner
from aria.retrieval.memory import IncidentMemory
from aria.retrieval.runbooks import load_runbooks
from aria.retrieval.seed import incident_from_scenario
from aria.security.redaction import Redactor
from aria.services import Services
from aria.severity import recalibration
from aria.severity.conformal import FAMILIAR
from aria.severity.model import Calibration, LinearModel
from aria.severity.recalibration import (
    ReviewedExample,
    adapt_from_blind_checks,
    recalibrate_from_feedback,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
KINDS = [
    "review",
    "edit",
    "publish",
    "send",
    "blind_check",
    "recalibration",
    "model_swap",
    "purge",
    "delete",
]
CLASSES = ["SEV1", "SEV2", "SEV3", "SEV4"]


def kinds_of(entries: list[DecisionRecord]) -> list[str]:
    return [entry.kind for entry in entries]


# --- the chain ------------------------------------------------------------------------------------


def test_entries_chain_from_the_genesis_hash_and_the_chain_verifies() -> None:
    engine = get_engine()
    init_db(engine)
    empty = record.verify(engine)
    assert (empty.ok, empty.length, empty.head_hash) == (True, 0, None)  # an empty record holds
    first = record.append(engine, kind="review", actor="ana", run_id="run-1", payload={"n": 1})
    second = record.append(engine, kind="publish", actor="ana", run_id="run-1", payload={"n": 2})
    third = record.append(engine, kind="recalibration", actor="system", payload={"n": 3})

    assert (first.seq, second.seq, third.seq) == (0, 1, 2)
    assert first.prev_hash == GENESIS
    assert (second.prev_hash, third.prev_hash) == (first.hash, second.hash)
    assert len({first.hash, second.hash, third.hash}) == 3
    assert first.hash == record.entry_hash(**first.model_dump(exclude={"hash"}))

    result = record.verify(engine)
    assert (result.ok, result.length, result.first_broken) == (True, 3, None)
    assert result.head_hash == third.hash
    assert record.list_entries(engine) == [first, second, third]
    assert record.list_entries(engine, run_id="run-1") == [first, second]
    assert record.list_entries(engine, after=0) == [second, third]
    assert record.list_entries(engine, limit=1) == [first]


def test_payloads_are_redacted_and_made_plain_before_they_are_hashed() -> None:
    engine = get_engine()
    init_db(engine)
    when = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
    entry = record.append(
        engine,
        kind="review",
        actor="ana <ana@example.com>",
        run_id="run-1",
        payload={
            "comment": "password=hunter2, told by ana@example.com from 10.0.0.7",
            "severity": Severity.SEV2,
            "at": when,
            "levels": {Severity.SEV1, Severity.SEV3},
        },
        redactor=Redactor(salt=b"a-run-salt"),
    )
    assert "hunter2" not in entry.payload["comment"]
    assert "[REDACTED]" in entry.payload["comment"]
    assert "ana@example.com" not in entry.payload["comment"]
    assert "ana@example.com" not in entry.actor
    assert "10.0.0.7" not in entry.payload["comment"]
    assert "ip-" in entry.payload["comment"]
    assert entry.payload["severity"] == "SEV2"
    assert entry.payload["at"] == when.isoformat()
    assert entry.payload["levels"] == ["SEV1", "SEV3"]
    # What was stored is what was hashed: reading it back verifies.
    assert record.list_entries(engine) == [entry]
    assert record.verify(engine).ok
    assert record.clipped("x" * 600) is not None
    assert len(record.clipped("x" * 600) or "") == record.TEXT_CHARS
    assert record.clipped(None) is None


def chain(items: list[tuple[str, str | None, str, dict[str, Any]]]) -> list[DecisionRecord]:
    """A chain built in memory, as ``append`` builds it in the database."""
    base = datetime(2026, 11, 1, tzinfo=UTC)
    out: list[DecisionRecord] = []
    prev = GENESIS
    for seq, (kind, run_id, actor, payload) in enumerate(items):
        entry = record.make_entry(
            seq=seq,
            ts=base + timedelta(seconds=seq),
            kind=kind,  # type: ignore[arg-type]
            run_id=run_id,
            actor=actor,
            payload=record.jsonable(payload),
            prev_hash=prev,
        )
        out.append(entry)
        prev = entry.hash
    return out


def flipped(digest: str) -> str:
    return ("1" if digest[0] == "0" else "0") + digest[1:]


facts = st.fixed_dictionaries(
    {},
    optional={
        "n": st.integers(min_value=-10, max_value=10),
        "text": st.text(max_size=12),
        "flag": st.booleans(),
    },
)
entries = st.tuples(
    st.sampled_from(KINDS),
    st.one_of(st.none(), st.text(min_size=1, max_size=8)),
    st.text(min_size=1, max_size=10),
    facts,
)
FIELDS = ["seq", "ts", "kind", "run_id", "actor", "payload", "prev_hash", "hash", "order"]


@given(items=st.lists(entries, min_size=1, max_size=6), data=st.data())
@settings(max_examples=200, deadline=None)
def test_any_change_to_an_entry_or_to_the_order_breaks_verification(
    items: list[tuple[str, str | None, str, dict[str, Any]]], data: st.DataObject
) -> None:
    built = chain(items)
    assert record.check(built).ok
    i = data.draw(st.integers(min_value=0, max_value=len(built) - 1))
    field = data.draw(st.sampled_from(FIELDS))
    tampered = list(built)
    entry = built[i]
    if field == "order":
        assume(len(built) > 1)
        j = data.draw(st.integers(min_value=0, max_value=len(built) - 1).filter(lambda j: j != i))
        tampered[i], tampered[j] = tampered[j], tampered[i]
        broken_at = min(i, j)
    else:
        changes: dict[str, Any] = {
            "seq": entry.seq + 1,
            "ts": entry.ts + timedelta(microseconds=1),
            "kind": next(k for k in KINDS if k != entry.kind),
            "run_id": (entry.run_id or "") + "x",
            "actor": entry.actor + "x",
            "payload": {**entry.payload, "tampered": True},
            "prev_hash": flipped(entry.prev_hash),
            "hash": flipped(entry.hash),
        }
        tampered[i] = entry.model_copy(update={field: changes[field]})
        broken_at = i
    result = record.check(tampered)
    assert not result.ok
    assert result.first_broken == broken_at
    assert result.problem


def test_concurrent_writers_keep_one_chain() -> None:
    engine = get_engine()
    init_db(engine)
    writers, each = 6, 10

    def write(n: int) -> None:
        for k in range(each):
            record.append(engine, kind="review", actor=f"w{n}", run_id=f"run-{n}", payload={"k": k})

    with ThreadPoolExecutor(max_workers=writers) as pool:
        list(pool.map(write, range(writers)))

    all_entries = record.list_entries(engine, limit=10_000)
    assert [e.seq for e in all_entries] == list(range(writers * each))
    assert len({e.hash for e in all_entries}) == writers * each
    assert record.verify(engine).ok
    for n in range(writers):  # each writer's own entries kept their order
        own = [e.payload["k"] for e in all_entries if e.actor == f"w{n}"]
        assert own == list(range(each))


def test_a_writer_that_read_a_stale_tail_tries_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two writers that read the same tail cannot both insert the next entry: the loser's insert
    fails on the primary key, and it reads the new tail and tries again."""
    engine = get_engine()
    init_db(engine)
    record.append(engine, kind="review", actor="ana", run_id="run-1")
    real = record._tail
    stale: list[bool] = []

    def tail(session: Any) -> tuple[int, str]:
        seq, prev = real(session)
        if not stale:  # the first look: another writer commits entry 1 just after it
            stale.append(True)
            record.append(engine, kind="publish", actor="raj", run_id="run-2")
        return seq, prev

    monkeypatch.setattr(record, "_tail", tail)
    entry = record.append(engine, kind="edit", actor="ana", run_id="run-1")
    assert entry.seq == 2
    assert kinds_of(record.list_entries(engine)) == ["review", "publish", "edit"]
    assert record.verify(engine).ok


def test_a_decision_that_cannot_be_recorded_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = get_engine()
    init_db(engine)
    monkeypatch.setattr(record, "ATTEMPTS", 2)
    monkeypatch.setattr(record, "_tail", lambda session: (0, GENESIS))  # always stale
    record.append(engine, kind="review", actor="ana")
    with pytest.raises(record.RecordError, match="after 2 attempts"):
        record.append(engine, kind="review", actor="ana")
    assert record.verify(engine).length == 1


# --- append-only ----------------------------------------------------------------------------------


def test_the_record_refuses_updates_and_deletes_on_sqlite() -> None:
    engine = get_engine()
    init_db(engine)
    entry = record.append(engine, kind="review", actor="ana", run_id="run-1")
    for statement in (
        "UPDATE decision_record SET actor = 'mallory' WHERE seq = 0",
        "DELETE FROM decision_record WHERE seq = 0",
        "DELETE FROM decision_record",
    ):
        with pytest.raises(IntegrityError, match="append-only"), session_scope(engine) as session:
            session.execute(text(statement))

    def delete_through_the_orm() -> None:
        with session_scope(engine) as session:
            row = session.get(DecisionRecordRow, 0)
            assert row is not None
            session.delete(row)

    with pytest.raises(IntegrityError, match="append-only"):
        delete_through_the_orm()
    assert record.list_entries(engine) == [entry]
    assert not hasattr(record, "update_entry")  # the module offers no way to change the past
    assert not hasattr(record, "delete_entry")


def test_a_rewritten_or_removed_entry_is_found_even_without_the_triggers() -> None:
    """Whoever administers the database can drop the triggers. The hashes still tell."""
    engine = get_engine()
    init_db(engine)
    for n in range(4):
        record.append(engine, kind="review", actor="ana", run_id=f"run-{n}")
    head = record.verify(engine).head_hash
    with session_scope(engine) as session:
        session.execute(text("DROP TRIGGER decision_record_no_update"))
        session.execute(text("DROP TRIGGER decision_record_no_delete"))
        session.execute(text("UPDATE decision_record SET actor = 'mallory' WHERE seq = 2"))
    rewritten = record.verify(engine)
    assert (rewritten.ok, rewritten.first_broken) == (False, 2)
    assert rewritten.problem == "entry 2 does not match its own hash"
    with session_scope(engine) as session:
        session.execute(text("UPDATE decision_record SET actor = 'ana' WHERE seq = 2"))
        session.execute(text("DELETE FROM decision_record WHERE seq = 1"))
    removed = record.verify(engine)
    assert (removed.ok, removed.first_broken, removed.problem) == (False, 1, "entry 1 is missing")
    # Cutting the tail off leaves a chain that holds, but not the head hash that was anchored.
    with session_scope(engine) as session:
        session.execute(text("DELETE FROM decision_record WHERE seq = 3"))
        session.execute(text("DELETE FROM decision_record WHERE seq = 2"))
    cut = record.verify(engine)
    assert (cut.ok, cut.length) == (True, 1)
    assert cut.head_hash != head


# --- the migration --------------------------------------------------------------------------------


def test_the_migration_adds_the_record_and_can_be_undone(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'old.db'}"
    migrate.upgrade("c6e1d4a9b2f7", url=url)
    engine = create_engine(url)
    assert "decision_record" not in inspect(engine).get_table_names()

    migrate.upgrade("head", url=url)
    assert "decision_record" in inspect(engine).get_table_names()
    indexes = {index["name"] for index in inspect(engine).get_indexes("decision_record")}
    assert "ix_decision_record_run_id" in indexes
    with engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'decision_record' ORDER BY name"
            )
        ).scalars()
        assert list(triggers) == ["decision_record_no_delete", "decision_record_no_update"]
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "e8f2a7c3d9b1"
    record.append(engine, kind="review", actor="ana", run_id="run-1")
    with pytest.raises(IntegrityError, match="append-only"), engine.begin() as conn:
        conn.execute(text("UPDATE decision_record SET actor = 'mallory'"))
    assert record.verify(engine).ok

    migrate.downgrade("c6e1d4a9b2f7", url=url)
    assert "decision_record" not in inspect(engine).get_table_names()
    with engine.connect() as conn:
        left = conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).all()
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert left == []
    assert version == "c6e1d4a9b2f7"
    migrate.upgrade("head", url=url)
    assert record.verify(engine).length == 0  # a new, empty record
    engine.dispose()


# --- every decision path --------------------------------------------------------------------------


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
    seeded = builder.build("bgl.kernel_panic", seed=7, nodes=3, duration_min=5)
    await IncidentMemory(engine, None).bulk_insert([incident_from_scenario(seeded, runbooks)])
    services = await Services.create()
    yield Env(TriageRunner(services), services, builder)
    await services.aclose()


def kernel_panic(env: Env, seed: int = 8, **fields: Any) -> TriageRequest:
    scenario = env.builder.build(
        "bgl.kernel_panic", seed=seed, nodes=4, duration_min=6, incident_per_min=8
    )
    return TriageRequest(
        title="Kernel panics", system="bgl", logs=scenario.lines, synthetic=True, **fields
    )


def action_of(interrupt: dict[str, Any], audience: str) -> str:
    return str(next(a["action_id"] for a in interrupt["actions"] if a["audience"] == audience))


async def test_an_approval_its_messages_a_resend_and_a_deletion_are_all_recorded(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook_url = "https://hooks.example.test/aria"
    monkeypatch.setenv("ARIA_OUTBOUND_WEBHOOK_URL", hook_url)
    engine = env.engine
    outcome = await env.runner.start(kernel_panic(env))
    assert outcome.interrupt is not None
    run_id = outcome.run_id
    hook = action_of(outcome.interrupt, "stakeholders")
    assert record.list_entries(engine, run_id=run_id) == []  # nothing decided yet

    with respx.mock() as mock:
        mock.post(hook_url).mock(return_value=httpx.Response(503))  # the receiver is down
        done = await env.runner.resume(
            run_id,
            {
                "decision": "approve",
                "reviewer": "ana",
                "comment": "Looks right. Token xoxb-1234567890-abcdef was in the logs.",
                "approve_actions": [hook],
            },
        )
    assert done.status is RunStatus.PUBLISHED
    entries = record.list_entries(engine, run_id=run_id)
    assert kinds_of(entries) == ["review", "publish", "send"]
    review, publish, send = entries
    assert review.actor == publish.actor == send.actor == "ana"
    assert review.payload["decision"] == "approve"
    assert review.payload["approved_actions"] == [hook]
    assert review.payload["from_severity"] == review.payload["to_severity"]
    assert review.payload["to_severity"] == outcome.interrupt["severity"]
    assert "xoxb-" not in review.payload["comment"]
    assert "[REDACTED]" in review.payload["comment"]
    assert publish.payload["report_id"] == f"rpt-{run_id}"
    assert publish.payload["severity"] == review.payload["to_severity"]
    assert publish.payload["generated_by"] in ("template", "llm")
    assert (send.payload["action_id"], send.payload["status"]) == (hook, "failed")
    assert send.payload["channel"] == "webhook"
    assert "body" not in send.payload  # the message's text stays in the action row

    with respx.mock() as mock:
        mock.post(hook_url).mock(return_value=httpx.Response(202))
        await env.runner.resend(run_id, hook, by="ben")
    resent = record.list_entries(engine, run_id=run_id)[-1]
    assert (resent.kind, resent.actor) == ("send", "ben")
    assert (resent.payload["status"], resent.payload["resent"]) == ("sent", True)

    await env.runner.delete(run_id, by="ana")
    assert repo.get_run(engine, run_id) is None
    kept = record.list_entries(engine, run_id=run_id)
    assert kinds_of(kept) == ["review", "publish", "send", "send", "delete"]
    assert kept[-1].payload["status"] == "published"
    assert record.verify(engine).ok


async def test_an_edit_records_the_decision_and_what_changed(env: Env) -> None:
    outcome = await env.runner.start(kernel_panic(env))
    assert outcome.interrupt is not None
    other = "SEV4" if outcome.interrupt["severity"] != "SEV4" else "SEV3"
    done = await env.runner.resume(
        outcome.run_id,
        {
            "decision": "edit",
            "reviewer": "raj",
            "edits": {"severity": other, "note": "Only one node was affected."},
        },
    )
    assert done.status is RunStatus.PUBLISHED
    entries = record.list_entries(env.engine, run_id=outcome.run_id)
    assert kinds_of(entries) == ["review", "edit", "publish"]
    review, edit, publish = entries
    assert review.payload["decision"] == "edit"
    assert (review.payload["from_severity"], review.payload["to_severity"]) == (
        outcome.interrupt["severity"],
        other,
    )
    assert edit.actor == "raj"
    assert edit.payload["severity"] == other
    assert edit.payload["note"] == "Only one node was affected."
    assert (edit.payload["summary_lines"], edit.payload["actions_added"]) == (0, 0)
    assert publish.payload["severity"] == other


async def test_a_rejection_is_recorded_and_nothing_is_published(env: Env) -> None:
    outcome = await env.runner.start(kernel_panic(env))
    assert outcome.interrupt is not None
    done = await env.runner.resume(
        outcome.run_id, {"decision": "reject", "reviewer": "ana", "comment": "duplicate"}
    )
    assert done.status is RunStatus.REJECTED
    entries = record.list_entries(env.engine, run_id=outcome.run_id)
    assert kinds_of(entries) == ["review"]
    assert entries[0].payload["decision"] == "reject"
    assert entries[0].payload["comment"] == "duplicate"


async def test_an_unattended_approval_is_recorded_as_the_systems(env: Env) -> None:
    env.services.settings = env.services.settings.model_copy(update={"require_approval": False})
    done = await env.runner.start(kernel_panic(env, options=RunOptions(require_approval=False)))
    assert done.status is RunStatus.PUBLISHED
    entries = record.list_entries(env.engine, run_id=done.run_id)
    assert kinds_of(entries) == ["review", "publish"]
    assert {entry.actor for entry in entries} == {"system"}
    assert entries[0].payload["reviewer"] == "aria:auto"


async def test_a_review_that_cannot_be_recorded_fails_the_run_loudly(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = await env.runner.start(kernel_panic(env))
    assert outcome.interrupt is not None

    def refuse(*args: Any, **kwargs: Any) -> DecisionRecord:
        msg = "could not record the review decision: the disk is full"
        raise record.RecordError(msg)

    monkeypatch.setattr(workflow.record, "append", refuse)
    done = await env.runner.resume(outcome.run_id, {"decision": "approve", "reviewer": "ana"})
    assert done.status is RunStatus.FAILED
    assert "could not record the review decision" in (done.error or "")
    assert (repo.get_run(env.engine, outcome.run_id) or {})["status"] == "failed"
    assert record.list_entries(env.engine, run_id=outcome.run_id) == []


# --- recalibration and model swaps ----------------------------------------------------------------


def tiny_model(conformal_q: float) -> LinearModel:
    return LinearModel(
        name="tiny",
        classes=CLASSES,
        feature_names=["x"],
        mean=np.array([0.0]),
        scale=np.array([1.0]),
        coef=np.array([[3.0], [1.0], [-1.0], [-3.0]]),
        intercept=np.zeros(4),
        conformal_q=conformal_q,
        version="tiny-1",
    )


def examples(model: LinearModel, n: int, *, seed: int) -> list[ReviewedExample]:
    rng = np.random.default_rng(seed)
    out: list[ReviewedExample] = []
    for i in range(n):
        x = float(rng.uniform(-2, 2))
        top = int(np.argmax(model.predict_proba(model.matrix([{"x": x}]))[0]))
        label = top if rng.random() >= 0.4 else min(3, top + 1) if top < 3 else 2
        out.append(ReviewedExample(i, {"x": x}, CLASSES[label], used=False))
    return out


def calibrated_tiny(alpha: float) -> LinearModel:
    model = tiny_model(conformal_q=0.2)
    rng = np.random.default_rng(9)
    xs = rng.uniform(-2, 2, size=300)
    probs = model.predict_proba(model.matrix([{"x": float(x)} for x in xs]))
    tops = probs.argmax(axis=1)
    scores = {
        cls: sorted(float(1 - probs[i, k]) for i in range(len(xs)) if tops[i] == k)
        for k, cls in enumerate(CLASSES)
    }
    model.calibrations = {
        FAMILIAR: Calibration(
            temperature=1.0,
            alphas=dict.fromkeys(CLASSES, alpha),
            scores=scores,
            guard_classes=["SEV1", "SEV2"],
            ordered=True,
        )
    }
    return model


def test_a_recalibration_on_reviews_is_recorded_but_a_dry_run_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = get_engine()
    init_db(engine)
    path = tmp_path / "severity_log.json"
    model = tiny_model(conformal_q=0.2)
    model.save(path)
    monkeypatch.setattr(
        recalibration, "reviewed_examples", lambda db, model: examples(model, 60, seed=2)
    )
    monkeypatch.setattr(repo, "mark_feedback_used", lambda db, ids: None)

    assert recalibrate_from_feedback(engine, path, alpha=0.1, min_new_reviews=10, dry_run=True)
    assert record.list_entries(engine) == []
    result = recalibrate_from_feedback(engine, path, alpha=0.1, min_new_reviews=10, actor="cli")
    assert result is not None
    entries = record.list_entries(engine)
    assert kinds_of(entries) == ["recalibration"]
    entry = entries[0]
    assert (entry.actor, entry.run_id) == ("cli", None)
    assert entry.payload["method"] == "reviews"
    assert (entry.payload["from_version"], entry.payload["model_version"]) == (
        "tiny-1",
        result.model.version,
    )
    assert entry.payload["reviewed"] == 60
    assert entry.payload["file"] == "severity_log.json"


def test_a_recalibration_on_blind_checks_is_recorded(tmp_path: Path) -> None:
    engine = get_engine()
    init_db(engine)
    trained = tmp_path / "severity_log.json"
    calibrated_tiny(alpha=0.1).save(trained)
    live = tmp_path / "live" / "severity_log.json"
    model = calibrated_tiny(0.1)
    rng = np.random.default_rng(10)
    for i in range(12):
        x = float(rng.uniform(-2, 2))
        top = int(np.argmax(model.predict_proba(model.matrix([{"x": x}]))[0]))
        label = CLASSES[top if rng.random() >= 0.5 else (top + 1 if top < 3 else 2)]
        repo.save_feedback(
            engine,
            f"run-{i}",
            "blind_check",
            {"to": label, "model_row": {"x": x}, "calibration": FAMILIAR},
            author="ana",
        )
    targets = dict.fromkeys(CLASSES, 0.1)
    assert adapt_from_blind_checks(engine, live, targets=targets, trained=trained, dry_run=True)
    assert record.list_entries(engine) == []
    result = adapt_from_blind_checks(engine, live, targets=targets, trained=trained)
    assert result is not None
    entries = record.list_entries(engine)
    assert kinds_of(entries) == ["recalibration"]
    assert entries[0].actor == "system"
    assert entries[0].payload["method"] == "blind_checks"
    assert entries[0].payload["applied"] == 12
    assert entries[0].payload["model_version"] == result["model_version"]


async def test_a_running_engine_records_the_model_it_swaps_to(tmp_path: Path) -> None:
    engine = get_engine()
    init_db(engine)
    services = await Services.create()
    try:
        trained_file = services.config.severity.log_model_file
        path = tmp_path / "severity_log.json"
        shutil.copy(trained_file, path)  # never touch the committed model
        services.severity.model_path = path
        before = services.severity.model
        assert before is not None
        # A recalibration of the model this release trained, as the job would write one.
        swapped = replace(
            LinearModel.load(path),
            version=f"{before.version}-swapped",
            metadata={**before.metadata, "trained_version": before.trained_version},
        )
        swapped.save(path)
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 1_000_000))
        assert services.severity.refresh()
    finally:
        await services.aclose()
    entries = record.list_entries(engine)
    assert kinds_of(entries) == ["model_swap"]
    assert entries[0].actor == "system"
    assert entries[0].payload == {
        "from_version": before.version,
        "model_version": f"{before.version}-swapped",
        "file": "severity_log.json",
    }


# --- the routes and the command -------------------------------------------------------------------


ANA = {"Authorization": "Bearer k-ana"}


@dataclass
class Api:
    client: httpx.AsyncClient
    builder: ScenarioBuilder
    engine: Any


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Api]:
    monkeypatch.setenv("ARIA_API_KEYS", "ana:k-ana")
    reset_caches()
    engine = get_engine()
    init_db(engine)
    builder = ScenarioBuilder(LinePools.from_loghub(FIXTURES))
    runbooks = load_runbooks(Path("runbooks"))
    seeded = builder.build("bgl.kernel_panic", seed=7, nodes=3, duration_min=5)
    await IncidentMemory(engine, None).bulk_insert([incident_from_scenario(seeded, runbooks)])
    app_ = create_app()
    async with LifespanManager(app_) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:8000", headers=ANA, timeout=60
        ) as client:
            yield Api(client, builder, engine)


async def reviewed(api: Api) -> dict[str, Any]:
    scenario = api.builder.build("bgl.kernel_panic", seed=8, nodes=4, duration_min=6)
    body = {"system": "bgl", "title": "Kernel panics", "logs": scenario.lines}
    created = await api.client.post("/api/v1/runs", json=body)
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]
    for _ in range(600):
        detail: dict[str, Any] = (await api.client.get(f"/api/v1/runs/{run_id}")).json()
        if detail["status"] == "awaiting_review":
            return detail
        await asyncio.sleep(0.05)
    msg = f"run {run_id} stayed {detail['status']}"
    raise AssertionError(msg)


async def test_the_routes_show_a_runs_record_and_verify_the_chain(api: Api) -> None:
    run = await reviewed(api)
    run_id = run["id"]
    assert (await api.client.get(f"/api/v1/runs/{run_id}/record")).json() == []
    empty = (await api.client.get("/api/v1/audit/verify")).json()
    assert (empty["ok"], empty["length"], empty["head_hash"]) == (True, 0, None)

    rated = await api.client.post(f"/api/v1/blind-check/{run_id}", json={"severity": "SEV2"})
    assert rated.status_code == 200, rated.text
    done = await api.client.post(
        f"/api/v1/runs/{run_id}/review", json={"decision": "approve", "reviewer": "someone else"}
    )
    assert done.status_code == 200, done.text

    listed = await api.client.get(f"/api/v1/runs/{run_id}/record")
    assert listed.status_code == 200
    entries = listed.json()
    assert [e["kind"] for e in entries] == ["blind_check", "review", "publish"]
    assert {e["actor"] for e in entries} == {"ana"}  # the key's name, never the body's
    assert [e["seq"] for e in entries] == [0, 1, 2]
    assert entries[0]["payload"]["to"] == "SEV2"
    assert entries[0]["payload"]["aria"] == run["severity"]
    assert entries[0]["payload"]["held"] == ("SEV2" in run["review"]["prediction_set"])
    assert entries[1]["prev_hash"] == entries[0]["hash"]
    assert len(entries[2]["hash"]) == 64
    after = await api.client.get(f"/api/v1/runs/{run_id}/record", params={"after": 1})
    assert [e["seq"] for e in after.json()] == [2]
    limited = await api.client.get(f"/api/v1/runs/{run_id}/record", params={"limit": 1})
    assert [e["seq"] for e in limited.json()] == [0]
    assert (
        await api.client.get(f"/api/v1/runs/{run_id}/record", params={"limit": 0})
    ).status_code == 422
    assert (await api.client.get("/api/v1/runs/no-such-run/record")).status_code == 404

    check = (await api.client.get("/api/v1/audit/verify")).json()
    assert (check["ok"], check["length"], check["first_broken"]) == (True, 3, None)
    assert check["head_hash"] == entries[-1]["hash"]
    assert check["checked_at"]

    assert (await api.client.delete(f"/api/v1/runs/{run_id}")).status_code == 204
    assert (await api.client.get(f"/api/v1/runs/{run_id}/record")).status_code == 404
    kept = record.list_entries(api.engine, run_id=run_id)
    assert kinds_of(kept) == ["blind_check", "review", "publish", "delete"]
    assert kept[-1].actor == "ana"
    assert (await api.client.get("/api/v1/audit/verify")).json()["length"] == 4

    # Like every other route under /api, it needs a key once keys are set.
    anonymous = await api.client.get("/api/v1/audit/verify", headers={"Authorization": ""})
    assert anonymous.status_code == 401


def said(output: str) -> str:
    return " ".join(output.split())


def test_the_verify_command_reports_the_chain_and_the_first_broken_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = CliRunner()
    monkeypatch.setenv("ARIA_DATABASE_URL", f"sqlite:///{tmp_path / 'fresh.db'}")
    reset_caches()
    missing = cli.invoke(app, ["audit", "verify"])
    assert missing.exit_code == 1
    assert "aria db upgrade" in said(missing.output)

    engine = get_engine()
    init_db(engine)
    empty = cli.invoke(app, ["audit", "verify"])
    assert empty.exit_code == 0, empty.output
    assert "holds 0 entries and every link holds" in said(empty.output)

    record.append(engine, kind="review", actor="ana", run_id="run-1")
    head = record.append(engine, kind="publish", actor="ana", run_id="run-1").hash
    fine = cli.invoke(app, ["audit", "verify"])
    assert fine.exit_code == 0, fine.output
    assert "holds 2 entries and every link holds" in said(fine.output)
    assert head in said(fine.output)

    with session_scope(engine) as session:
        session.execute(text("DROP TRIGGER decision_record_no_update"))
        session.execute(text("UPDATE decision_record SET kind = 'edit' WHERE seq = 1"))
    broken = cli.invoke(app, ["audit", "verify"])
    assert broken.exit_code == 1
    assert "broken at entry 1: entry 1 does not match its own hash" in said(broken.output)
    assert "ops-runbook" in said(broken.output)
    assert "Traceback" not in broken.output
    with session_scope(engine) as session:
        assert session.scalar(select(DecisionRecordRow.kind).where(DecisionRecordRow.seq == 1))
