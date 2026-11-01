"""Periodic jobs that run beside the run executor: the log scan and model recalibration.

They start where runs execute, so a deployment runs each job once per executing process: the API
in ``inprocess`` mode, ``aria worker`` in ``external`` mode.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

from aria.api.scan import LogScanner, scan_forever
from aria.graph.runner import TriageRunner
from aria.observability.logging import get_logger
from aria.services import Services
from aria.severity.conformal import level_alphas
from aria.severity.model import live_model_path
from aria.severity.recalibration import adapt_from_blind_checks, recalibrate_from_feedback

log = get_logger(__name__)


async def recalibrate_forever(
    services: Services, *, interval_s: float, stop: asyncio.Event
) -> None:
    """Check for enough new reviews every interval and recalibrate the severity model."""
    config = services.config.severity
    while not stop.is_set():
        try:
            live = live_model_path(config.log_model_file, services.settings.models_dir)
            model = services.severity.model
            if model is not None and model.calibrations:
                # Per-level models learn from blind checks (ADR 0014), not approvals.
                adapted = await asyncio.to_thread(
                    adapt_from_blind_checks,
                    services.engine,
                    live,
                    targets=level_alphas(model.classes, config.alpha, config.serious_alpha),
                    trained=config.log_model_file,
                )
                if adapted is not None:
                    services.severity.refresh()
            else:
                result = await asyncio.to_thread(
                    recalibrate_from_feedback,
                    services.engine,
                    live,
                    alpha=config.alpha,
                    min_new_reviews=config.recalibrate_after,
                    trained=config.log_model_file,
                )
                if result is not None:
                    services.severity.refresh()
        except Exception:  # a failed check must not stop the job; the next one retries
            log.exception("severity.recalibration_failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_s)


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
    if services.config.severity.recalibrate_check_s > 0:
        tasks.append(
            asyncio.create_task(
                recalibrate_forever(
                    services, interval_s=services.config.severity.recalibrate_check_s, stop=stop
                ),
                name="aria-recalibrate",
            )
        )
    return tasks
