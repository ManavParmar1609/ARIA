"""Command-line entry points that the containers rely on."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aria.cli import WORKER_HEARTBEAT, app
from aria.config import reset_caches


def test_worker_health_needs_a_recent_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path))
    reset_caches()
    runner = CliRunner()
    missing = runner.invoke(app, ["worker-health"])
    assert missing.exit_code == 1
    assert "never" in missing.output
    beat = tmp_path / WORKER_HEARTBEAT
    beat.touch()
    fresh = runner.invoke(app, ["worker-health"])
    assert fresh.exit_code == 0, fresh.output
    old = time.time() - 600
    os.utime(beat, (old, old))
    assert runner.invoke(app, ["worker-health", "--max-age", "60"]).exit_code == 1
