"""Server-sent events for a run: replay what is stored, then follow it live.

A client that reconnects with ``Last-Event-ID`` gets every stored event after that sequence
number and then the live stream, with no gap and no duplicates (events are de-duplicated by
sequence number). LLM tokens are live only and carry no id, so a reconnect resumes from the last
stored event. When the run is executed by another process (the external worker), new events are
picked up by polling the database.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from aria.contracts.run import RunEvent, RunStatus
from aria.db import repository as repo
from aria.graph.runner import TriageRunner

# A stream ends after this long; a browser reconnects with Last-Event-ID, a forgotten tab stops.
MAX_STREAM_S = 3_600.0
# While a run waits for a person, nothing happens until they decide, so a stream looks for news
# this many times less often. A decision taken in this process still arrives at once.
PAUSED_POLL_FACTOR = 10
# Events that can follow the pause without ending it: the run's usage summary comes just after.
_STILL_PAUSED = frozenset({"interrupt", "budget", "checkpoint"})


def _message(event: RunEvent) -> dict[str, Any]:
    data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    if event.kind == "token":
        return {"event": "token", "data": data}
    return {"event": event.kind, "id": str(event.seq), "data": data}


async def run_events(
    runner: TriageRunner,
    run_id: str,
    *,
    after: int = -1,
    poll_s: float = 1.0,
    follow: bool = True,
    until_review: bool = False,
    max_s: float = MAX_STREAM_S,
) -> AsyncIterator[dict[str, Any]]:
    """Events for ``run_id``. Ends at ``run_finished``, at the review pause if asked, when the
    run is deleted, or after ``max_s``."""
    queue = runner.subscribe(run_id)
    last = after
    try:
        for event in await asyncio.to_thread(repo.list_events, runner.engine, run_id, after=last):
            yield _message(event)
            last = event.seq
            if event.kind == "run_finished":
                return
        if not follow:
            return
        run = await asyncio.to_thread(repo.get_run, runner.engine, run_id)
        if run is None or RunStatus(run["status"]).terminal:
            return
        if until_review and run["status"] == RunStatus.AWAITING_REVIEW:
            return
        paused = run["status"] == RunStatus.AWAITING_REVIEW
        loop = asyncio.get_running_loop()
        ends = loop.time() + max_s
        while loop.time() < ends:
            try:
                wait = poll_s * PAUSED_POLL_FACTOR if paused else poll_s
                event = await asyncio.wait_for(queue.get(), timeout=wait)
            except TimeoutError:
                stored = await asyncio.to_thread(
                    repo.list_events, runner.engine, run_id, after=last
                )
                for item in stored:
                    yield _message(item)
                    last = item.seq
                    paused = item.kind in _STILL_PAUSED and (paused or item.kind == "interrupt")
                    if item.kind == "run_finished":
                        return
                if until_review and any(item.kind == "interrupt" for item in stored):
                    return
                if (
                    not stored
                    and await asyncio.to_thread(repo.get_run, runner.engine, run_id) is None
                ):
                    return  # the run was deleted: nothing more will come
                continue
            if event.kind == "token":
                yield _message(event)
            elif event.seq > last:
                yield _message(event)
                last = event.seq
                paused = event.kind in _STILL_PAUSED and (paused or event.kind == "interrupt")
                if event.kind == "run_finished":
                    return
                if until_review and event.kind == "interrupt":
                    # The run's usage summary follows the pause within milliseconds; include it.
                    async for item in _drain(queue, after=last, grace_s=0.5):
                        yield _message(item)
                    return
    finally:
        runner.unsubscribe(run_id, queue)


async def _drain(
    queue: asyncio.Queue[RunEvent], *, after: int, grace_s: float
) -> AsyncIterator[RunEvent]:
    deadline = asyncio.get_running_loop().time() + grace_s
    while (left := deadline - asyncio.get_running_loop().time()) > 0:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=left)
        except TimeoutError:
            return
        if event.kind != "token" and event.seq > after:
            after = event.seq
            yield event
            if event.kind == "budget":
                return
