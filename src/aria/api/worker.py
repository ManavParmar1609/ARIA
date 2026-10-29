"""Background execution of runs.

``inprocess`` (the default): the API process runs triage in background tasks, a few at a time,
and on startup continues runs a previous process left unfinished. ``external``: the API only
records runs; ``aria worker`` processes claim them from the database. Either way a review
decision is applied by whichever process receives it: the checkpoints live in the shared
database, so any process can resume a paused run.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
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
        self._slots = asyncio.Semaphore(concurrency)
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def active(self) -> int:
        return len(self._tasks)

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
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def execute(self, run_id: str) -> asyncio.Task[Any]:
        return self.spawn(run_id, lambda: self.runner.execute(run_id))

    async def recover(self) -> list[str]:
        """Continue runs a stopped in-process worker left queued or running."""
        run_ids = await asyncio.to_thread(repo.unfinished_runs, self.runner.engine)
        for run_id in run_ids:
            self.execute(run_id)
        if run_ids:
            log.info("worker.recovered", runs=len(run_ids))
        return run_ids

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


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def heartbeat_age(path: Path) -> float | None:
    """Seconds since the worker last polled, or None when it never has."""
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except FileNotFoundError:
        return None


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

    After each poll that reaches the database, ``heartbeat`` (when given) is touched, so a
    container health check can tell a live worker from a stuck one."""
    me = worker_id()
    worker = Worker(runner, concurrency=concurrency)
    stop = stop or asyncio.Event()
    background = start_background_jobs(runner.services, runner, stop)
    log.info("worker.started", worker=me, concurrency=concurrency, jobs=len(background))
    try:
        while not stop.is_set():
            free = max(0, concurrency - worker.active)
            if free:
                claimed = await asyncio.to_thread(repo.claim_runs, runner.engine, me, limit=free)
                for run_id in claimed:
                    worker.execute(run_id)
            if heartbeat is not None:
                await asyncio.to_thread(_touch, heartbeat)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
    finally:
        stop.set()
        await asyncio.gather(*background, return_exceptions=True)
        await worker.drain()
        log.info("worker.stopped", worker=me)
