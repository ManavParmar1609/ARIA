"""The periodic log scan: a trigger for incidents no alert caught.

Every ``triggers.scan_interval_s`` seconds the scan reads the lines appended to each configured
log file and keeps the most recent ``scan_window_lines`` of them. It parses that window with the
production parser (redaction and the injection guard included) and, when the window's error
burst score reaches ``scan_min_burst_score``, reports a finding and starts the next window afresh,
so one burst opens one run. A file is read from where the scan stopped; the first look starts at
its end (history is not an incident), and a file that shrinks (rotated or truncated) is read from
the top. A finding opens a run with trigger ``scan``, unless a scan run on that system is still
open or started within the alert grouping window.

The scan runs where runs execute: in the API process in ``inprocess`` mode, in ``aria worker``
otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aria.config import GuardrailConfig, ScanSource, TriggerConfig
from aria.contracts.inputs import TriageRequest
from aria.contracts.run import RunStatus
from aria.db import repository as repo
from aria.evidence import EvidenceStore
from aria.graph.runner import TriageRunner
from aria.observability.logging import get_logger
from aria.parsing.parser import parse_lines

log = get_logger(__name__)

TRIGGER = "scan"
# New bytes read from one file per poll; a bigger burst is read over the next polls.
MAX_READ_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class ScanFinding:
    system: str
    path: Path
    lines: list[str]
    burst_score: float


class LogScanner:
    """Tails log files and reports a window whose errors burst."""

    def __init__(
        self,
        sources: Sequence[ScanSource],
        *,
        guard: GuardrailConfig,
        min_burst: float,
        window_lines: int = 2000,
    ) -> None:
        self.sources = list(sources)
        self.guard = guard
        self.min_burst = min_burst
        self.window_lines = window_lines
        self._offsets: dict[Path, int] = {}
        self._windows: dict[Path, deque[str]] = {}

    @classmethod
    def from_config(cls, triggers: TriggerConfig, guard: GuardrailConfig) -> LogScanner:
        return cls(
            triggers.scan_sources,
            guard=guard,
            min_burst=triggers.scan_min_burst_score,
            window_lines=triggers.scan_window_lines,
        )

    def _read_new(self, path: Path) -> list[str]:
        """Complete lines appended since the last read; a partial last line waits for its end."""
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return []
        offset = self._offsets.get(path)
        if offset is None:
            self._offsets[path] = size
            return []
        if size < offset:
            offset = 0
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(min(max(0, size - offset), MAX_READ_BYTES))
        complete = data.rfind(b"\n") + 1
        if not complete and len(data) == MAX_READ_BYTES:  # one line longer than a read: skip it
            self._offsets[path] = offset + len(data)
            return []
        self._offsets[path] = offset + complete
        return data[:complete].decode("utf-8", errors="replace").splitlines()

    def _burst(self, system: str, lines: Sequence[str]) -> float:
        parsed = parse_lines(lines, system=system, guard=self.guard, evidence=EvidenceStore())
        return parsed.batch.features.burst_score

    def poll(self) -> list[ScanFinding]:
        findings: list[ScanFinding] = []
        for source in self.sources:
            new = [line for line in self._read_new(source.path) if line.strip()]
            if not new:
                continue
            window = self._windows.setdefault(source.path, deque(maxlen=self.window_lines))
            window.extend(new)
            score = self._burst(source.system, list(window))
            if score >= self.min_burst:
                findings.append(ScanFinding(source.system, source.path, list(window), score))
                window.clear()
        return findings


def _age_s(created_at: str) -> float:
    started = datetime.fromisoformat(created_at)
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return (datetime.now(UTC) - started).total_seconds()


def open_run(runner: TriageRunner, finding: ScanFinding, *, window_s: int) -> str | None:
    """Record a queued run for a finding, or None when a recent scan run covers its system."""
    latest = repo.latest_run(runner.engine, trigger=TRIGGER, system=finding.system)
    if latest is not None and (
        not RunStatus(latest["status"]).terminal or _age_s(latest["created_at"]) < window_s
    ):
        log.info("scan.covered", system=finding.system, run_id=latest["id"])
        return None
    request = TriageRequest(system=finding.system, logs=finding.lines)
    run_id = runner.submit(request, trigger=TRIGGER)
    log.info(
        "scan.run_opened",
        system=finding.system,
        run_id=run_id,
        burst_score=finding.burst_score,
        lines=len(finding.lines),
    )
    return run_id


async def scan_forever(
    scanner: LogScanner,
    runner: TriageRunner,
    *,
    interval_s: float,
    window_s: int,
    stop: asyncio.Event,
    on_run: Callable[[str], object] | None = None,
) -> None:
    """Poll until ``stop`` is set. ``on_run`` hears each run opened, to start it in-process; it
    must not block (the worker's ``execute`` schedules a task). Queued runs wait for a worker."""
    log.info("scan.started", sources=len(scanner.sources), interval_s=interval_s)
    while not stop.is_set():
        try:
            for finding in await asyncio.to_thread(scanner.poll):
                run_id = await asyncio.to_thread(open_run, runner, finding, window_s=window_s)
                if run_id is not None and on_run is not None:
                    on_run(run_id)
        except Exception:  # a bad file or line must not stop the scan
            log.exception("scan.failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
