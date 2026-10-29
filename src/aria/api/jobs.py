"""Periodic jobs that run beside the run executor: the log scan (and, later, model upkeep).

They start where runs execute, so a deployment runs each job once per executing process: the API
in ``inprocess`` mode, ``aria worker`` in ``external`` mode.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from aria.api.scan import LogScanner, scan_forever
from aria.graph.runner import TriageRunner
from aria.services import Services


def start_background_jobs(
    services: Services,
    runner: TriageRunner,
    stop: asyncio.Event,
    *,
    on_run: Callable[[str], object] | None = None,
) -> list[asyncio.Task[None]]:
    """Start the configured jobs; each stops when ``stop`` is set."""
    tasks: list[asyncio.Task[None]] = []
    triggers = services.config.triggers
    if triggers.scan_interval_s > 0 and triggers.scan_sources:
        scanner = LogScanner.from_config(triggers, services.config.guardrails)
        tasks.append(
            asyncio.create_task(
                scan_forever(
                    scanner,
                    runner,
                    interval_s=triggers.scan_interval_s,
                    window_s=triggers.alert_group_window_s,
                    stop=stop,
                    on_run=on_run,
                ),
                name="aria-scan",
            )
        )
    return tasks
