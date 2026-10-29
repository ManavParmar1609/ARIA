from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from aria.data.ingest import build_bgl_windows, ingest_loghub_samples
from aria.data.loghub import LogRecord
from aria.db.engine import get_engine, init_db, session_scope
from aria.db.models import LogEventRow, RunRow

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"


def test_datetimes_come_back_timezone_aware_utc() -> None:
    engine = get_engine()
    init_db(engine)
    ist = timezone(timedelta(hours=5, minutes=30))
    with session_scope(engine) as session:
        session.add(
            RunRow(id="r1", status="queued", created_at=datetime(2026, 1, 1, 12, 0, tzinfo=ist))
        )
    with session_scope(engine) as session:
        run = session.get(RunRow, "r1")
        assert run is not None
        assert run.created_at == datetime(2026, 1, 1, 6, 30, tzinfo=UTC)
        assert run.created_at.tzinfo is UTC


def test_session_scope_rolls_back_on_error() -> None:
    engine = get_engine()
    init_db(engine)

    def add_then_fail() -> None:
        with session_scope(engine) as session:
            session.add(RunRow(id="r2", status="queued"))
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        add_then_fail()
    with session_scope(engine) as session:
        assert session.get(RunRow, "r2") is None


def test_ingest_loghub_fixture_is_idempotent() -> None:
    engine = get_engine()
    init_db(engine)
    first = ingest_loghub_samples(engine, FIXTURES)
    second = ingest_loghub_samples(engine, FIXTURES)
    assert first.events == second.events > 0
    with session_scope(engine) as session:
        total = session.scalar(select(func.count()).select_from(LogEventRow))
        alerts = session.scalar(
            select(func.count()).select_from(LogEventRow).where(LogEventRow.label.is_not(None))
        )
    assert total == first.events
    assert alerts == 143  # every BGL alert line in the fixture


def test_bgl_windows_are_labelled_and_split_in_time_order() -> None:
    start = datetime(2005, 6, 3, tzinfo=UTC)
    records: list[LogRecord] = []
    for window in range(10):
        for i in range(8):
            label = "KERNRTSP" if window == 9 and i < 4 else None
            records.append(
                LogRecord(
                    system="bgl",
                    line_no=len(records) + 1,
                    message="rts panic! - stopping execution" if label else "generating core.1",
                    ts=start + timedelta(minutes=10 * window, seconds=i),
                    node=f"R0{i}-M0-N0",
                    label=label,
                )
            )
    windows, assignment = build_bgl_windows(records)
    assert len(windows) == 10
    assert [w["split"] for w in windows].count("train") == 6
    assert windows[-1]["label_severity"] == "SEV1"  # 4 nodes with critical alerts
    assert all(w["label_severity"] == "SEV4" for w in windows[:-1])
    assert len(assignment) == len(records)
