"""The periodic log scan: tailing files, spotting error bursts and opening one run per burst."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from aria.api.jobs import start_background_jobs
from aria.api.scan import TRIGGER, LogScanner, ScanFinding, open_run, scan_forever
from aria.config import GuardrailConfig, ScanSource, TriggerConfig
from aria.contracts.run import RunStatus
from aria.data.loghub import LogRecord, format_raw_line
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db
from aria.graph.runner import TriageRunner
from aria.services import Services

START = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
NODE = "R02-M1-N0-C:J12-U11"


def bgl(ts: datetime, level: str, message: str) -> str:
    record = LogRecord(
        system="bgl",
        line_no=0,
        message=message,
        ts=ts,
        node=NODE,
        fields={"Level": level, "Component": "KERNEL", "Type": "RAS"},
    )
    return format_raw_line(record)


def quiet(minutes: int, start: datetime = START) -> list[str]:
    """Routine lines, four a minute, with no errors."""
    return [
        bgl(start + timedelta(minutes=m, seconds=15 * i), "INFO", f"generating core.{m}{i}")
        for m in range(minutes)
        for i in range(4)
    ]


def burst(at: datetime, count: int = 40) -> list[str]:
    """A minute of fatal kernel errors."""
    return [
        bgl(at + timedelta(seconds=i), "FATAL", "rts: kernel terminated for reason 1004")
        for i in range(count)
    ]


def append(path: Path, lines: list[str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.writelines(line + "\n" for line in lines)


def scanner_for(path: Path, *, min_burst: float = 3.0) -> LogScanner:
    return LogScanner(
        [ScanSource(system="bgl", path=path)], guard=GuardrailConfig(), min_burst=min_burst
    )


def test_a_burst_is_reported_once_and_history_is_not(tmp_path: Path) -> None:
    log = tmp_path / "bgl.log"
    append(log, quiet(5) + burst(START + timedelta(minutes=5)))  # before the scan: history
    scan = scanner_for(log)
    assert scan.poll() == []

    later = START + timedelta(minutes=10)
    append(log, quiet(10, later))
    assert scan.poll() == []

    append(log, burst(later + timedelta(minutes=10)))
    [finding] = scan.poll()
    assert finding.system == "bgl"
    assert finding.burst_score >= 3.0
    assert len(finding.lines) == 40 + 40  # the quiet minutes give the burst its baseline
    assert scan.poll() == []  # the same burst never opens a second run

    append(log, quiet(5, later + timedelta(minutes=11)))
    assert scan.poll() == []


def test_lines_are_read_whole_and_a_rotated_file_from_the_top(tmp_path: Path) -> None:
    log = tmp_path / "bgl.log"
    log.touch()
    scan = scanner_for(log, min_burst=0.0)  # report every window, to see what was read
    assert scan.poll() == []

    first, second = quiet(1)[:2]
    with log.open("a", encoding="utf-8") as handle:
        handle.write(first + "\n" + second[:20])  # the second line is still being written
    [finding] = scan.poll()
    assert finding.lines == [first]
    with log.open("a", encoding="utf-8") as handle:
        handle.write(second[20:] + "\n")
    [finding] = scan.poll()
    assert finding.lines == [second]

    log.write_text(first + "\n", encoding="utf-8")  # rotated: shorter than what was read
    [finding] = scan.poll()
    assert finding.lines == [first]


def test_a_missing_file_is_skipped_until_it_appears(tmp_path: Path) -> None:
    log = tmp_path / "later.log"
    scan = scanner_for(log, min_burst=0.0)
    assert scan.poll() == []
    log.touch()
    assert scan.poll() == []  # first look: starts at the end
    append(log, quiet(1))
    assert len(scan.poll()) == 1


def test_sources_come_from_an_environment_string() -> None:
    triggers = TriggerConfig.model_validate(
        {"scan_sources": "bgl=/var/log/bgl.log, openssh=/var/log/auth.log"}
    )
    assert [(s.system, str(s.path)) for s in triggers.scan_sources] == [
        ("bgl", "/var/log/bgl.log"),
        ("openssh", "/var/log/auth.log"),
    ]
    assert TriggerConfig.model_validate({"scan_sources": ""}).scan_sources == []
    with pytest.raises(ValidationError):
        TriggerConfig.model_validate({"scan_sources": "bgl-without-a-path"})


@pytest.fixture
async def runner() -> AsyncIterator[TriageRunner]:
    init_db(get_engine())
    services = await Services.create()
    yield TriageRunner(services)
    await services.aclose()


def finding(lines: list[str]) -> ScanFinding:
    return ScanFinding(system="bgl", path=Path("bgl.log"), lines=lines, burst_score=12.0)


async def test_a_finding_opens_one_run_until_its_system_is_quiet(runner: TriageRunner) -> None:
    lines = quiet(2) + burst(START + timedelta(minutes=2))
    run_id = open_run(runner, finding(lines), window_s=300)
    assert run_id is not None
    run = repo.get_run(runner.engine, run_id)
    assert run is not None
    assert (run["trigger"], run["system"], run["status"]) == (TRIGGER, "bgl", "queued")
    assert run["request"]["logs"] == lines

    assert open_run(runner, finding(lines), window_s=300) is None  # still open

    repo.update_run(runner.engine, run_id, status=RunStatus.PUBLISHED)
    assert open_run(runner, finding(lines), window_s=300) is None  # finished, but just now
    assert open_run(runner, finding(lines), window_s=0) is not None


async def test_the_scan_loop_triages_a_burst_end_to_end(
    runner: TriageRunner, tmp_path: Path
) -> None:
    log = tmp_path / "bgl.log"
    log.touch()
    scan = scanner_for(log)
    scan.poll()
    append(log, quiet(10) + burst(START + timedelta(minutes=10)))

    stop = asyncio.Event()
    opened: list[str] = []

    def on_run(run_id: str) -> None:
        opened.append(run_id)
        stop.set()

    await asyncio.wait_for(
        scan_forever(scan, runner, interval_s=0.05, window_s=300, stop=stop, on_run=on_run),
        timeout=30,
    )
    [run_id] = opened
    outcome = await runner.execute(run_id)
    assert outcome.status is RunStatus.AWAITING_REVIEW
    run = repo.get_run(runner.engine, run_id)
    assert run is not None
    assert run["severity"] in {"SEV1", "SEV2"}  # fatal kernel errors on a compute node


async def test_jobs_start_only_when_the_scan_is_configured(
    runner: TriageRunner, tmp_path: Path
) -> None:
    stop = asyncio.Event()
    assert start_background_jobs(runner.services, runner, stop) == []

    triggers = runner.services.config.triggers
    configured = triggers.model_copy(
        update={
            "scan_interval_s": 60,
            "scan_sources": [ScanSource(system="bgl", path=tmp_path / "bgl.log")],
        }
    )
    runner.services.config = runner.services.config.model_copy(update={"triggers": configured})
    [task] = start_background_jobs(runner.services, runner, stop)
    assert task.get_name() == "aria-scan"
    stop.set()
    await asyncio.wait_for(task, timeout=5)
