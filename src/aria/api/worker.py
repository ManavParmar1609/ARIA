"""Background execution of runs.

``inprocess`` (the default): the API process runs triage in background tasks, a few at a time,
and keeps claiming runs a stopped process left unfinished. ``external``: the API only records
runs; ``aria worker`` processes claim them from the database. Either way a review decision is
applied by whichever process receives it: the checkpoints live in the shared database, so any
process can resume a paused run. Whoever drives a run claims it first (``TriageRunner._drive``),
so two processes never drive one run at once.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aria.api.jobs import start_background_jobs
from aria.db import repository as repo
from aria.graph.runner import RunBusyError, TriageRunner
from aria.observability.logging import get_logger

log = get_logger(__name__)


class Worker:
    """Runs coroutines for runs in the background with bounded concurrency."""

    def __init__(self, runner: TriageRunner, *, concurrency: int = 4) -> None:
        self.runner = runner
        self._capacity = concurrency
        self._slots = asyncio.Semaphore(concurrency)
        self._tasks: dict[asyncio.Task[Any], str] = {}

    @property
    def active(self) -> int:
        return len(self._tasks)

    @property
    def run_ids(self) -> list[str]:
        """Runs with a job in flight."""
        return sorted(set(self._tasks.values()))

    def spawn(self, run_id: str, job: Callable[[], Awaitable[Any]]) -> asyncio.Task[Any]:
        async def guarded() -> None:
            async with self._slots:
                try:
                    await job()
                except RunBusyError:
                    log.info("worker.busy", run_id=run_id)
                except Exception:  # the runner already recorded the failure on the run
                    log.exception("worker.job_failed", run_id=run_id)

        task = asyncio.create_task(guarded(), name=f"aria-run-{run_id}")
        self._tasks[task] = run_id
        task.add_done_callback(lambda done: self._tasks.pop(done, None))
        return task

    def execute(self, run_id: str) -> asyncio.Task[Any]:
        for task, held in self._tasks.items():
            if held == run_id:  # already waiting for a slot, or running: once is enough
                return task
        return self.spawn(run_id, lambda: self.runner.execute(run_id))

    async def gated[T](self, job: Awaitable[T]) -> T:
        """Await a run's job in one of the same slots the background jobs use.

        AG-UI and A2A run a triage inside the request that streams it; going through here means
        however many streams are open, no more runs execute at once than the worker allows.
        """
        async with self._slots:
            return await job

    async def recover(self, *, limit: int = 50) -> list[str]:
        """Claim and continue runs left queued, or held by a process that stopped renewing."""
        run_ids = await asyncio.to_thread(
            repo.claim_runs, self.runner.engine, self.runner.owner, limit=limit
        )
        self.runner.held.update(run_ids)
        for run_id in run_ids:
            self.execute(run_id)
        if run_ids:
            log.info("worker.recovered", runs=len(run_ids))
        return run_ids

    async def keep_claims(self, stop: asyncio.Event, *, recover: bool) -> None:
        """Renew this process's claims every ``CLAIM_RENEW_S`` until ``stop``; with ``recover``,
        also take over runs whose holder stopped (the in-process API has no worker to do it)."""
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=repo.CLAIM_RENEW_S)
            if stop.is_set():
                break
            try:
                await asyncio.to_thread(self.runner.renew_held)
                if recover:
                    await self.recover(limit=max(1, self._capacity - self.active))
                # Incidents another process published or deleted reach this one's memory.
                await self.runner.services.memory.refresh_if_changed()
            except Exception:  # a database blip: try again on the next round
                log.exception("worker.claims_failed")

    async def drain(self, grace_s: float = 30.0) -> None:
        """Wait for running jobs on shutdown, then cancel what is left."""
        if not self._tasks:
            return
        _, pending = await asyncio.wait(set(self._tasks), timeout=grace_s)
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


def heartbeat_file(data_dir: Path) -> Path:
    """This host's heartbeat: one file per container, even when they share a data volume."""
    return data_dir / f"worker-{socket.gethostname()}.heartbeat"


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def heartbeat_age(path: Path) -> float | None:
    """Seconds since the worker last polled, or None when it never has."""
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except FileNotFoundError:
        return None


async def serve_health(
    port: int,
    heartbeat: Path,
    *,
    max_age_s: float = 60.0,
    host: str = "0.0.0.0",  # noqa: S104 - a container probe reaches it from outside the loopback
) -> asyncio.Server:
    """A minimal HTTP liveness endpoint for platforms that probe over HTTP: any request gets 200
    while the worker polled within ``max_age_s`` (or is still starting), and 503 once it stops,
    so the platform restarts a hung worker."""
    started = time.monotonic()

    async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(reader.readline(), timeout=5)  # the request line is enough
            age = heartbeat_age(heartbeat)
            starting = age is None and time.monotonic() - started < 2 * max_age_s
            ok = starting or (age is not None and age <= max_age_s)
            body = json.dumps(
                {"status": "ok" if ok else "stale", "heartbeat_age_s": age, "starting": starting}
            ).encode()
            status = "200 OK" if ok else "503 Service Unavailable"
            head = (
                f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            )
            writer.write(head.encode() + body)
            await writer.drain()
        writer.close()

    return await asyncio.start_server(answer, host=host, port=port)


async def poll_forever(
    runner: TriageRunner,
    *,
    concurrency: int = 4,
    interval_s: float = 2.0,
    stop: asyncio.Event | None = None,
    heartbeat: Path | None = None,
) -> None:
    """The external worker loop: claim runs from the database and execute them, with the
    periodic jobs (the log scan) running beside it.

    Claims on runs this process holds are renewed every ``CLAIM_RENEW_S``, so another worker
    takes a run over only when this one has stopped. After each poll that reaches the database,
    ``heartbeat`` (when given) is touched, so a container health check can tell a live worker
    from a stuck one."""
    me = runner.owner
    worker = Worker(runner, concurrency=concurrency)
    stop = stop or asyncio.Event()
    background = start_background_jobs(runner.services, runner, stop)
    log.info("worker.started", worker=me, concurrency=concurrency, jobs=len(background))
    renewed = time.monotonic()
    try:
        while not stop.is_set():
            free = max(0, concurrency - worker.active)
            if free:
                claimed = await asyncio.to_thread(repo.claim_runs, runner.engine, me, limit=free)
                runner.held.update(claimed)
                for run_id in claimed:
                    worker.execute(run_id)
            if time.monotonic() - renewed >= repo.CLAIM_RENEW_S:
                await asyncio.to_thread(runner.renew_held)
                # Incidents the API published or deleted reach this worker's memory.
                await runner.services.memory.refresh_if_changed()
                renewed = time.monotonic()
            if heartbeat is not None:
                await asyncio.to_thread(_touch, heartbeat)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
    finally:
        stop.set()
        await asyncio.gather(*background, return_exceptions=True)
        await worker.drain()
        log.info("worker.stopped", worker=me)
