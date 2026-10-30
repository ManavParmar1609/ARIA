"""Command-line entry points that the containers rely on."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aria.api.worker import heartbeat_file
from aria.cli import app
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
    beat = heartbeat_file(tmp_path)
    beat.touch()
    fresh = runner.invoke(app, ["worker-health"])
    assert fresh.exit_code == 0, fresh.output
    old = time.time() - 600
    os.utime(beat, (old, old))
    assert runner.invoke(app, ["worker-health", "--max-age", "60"]).exit_code == 1


def test_recalibrate_says_when_there_is_nothing_to_do() -> None:
    from aria.db.engine import get_engine, init_db

    init_db(get_engine())
    result = CliRunner().invoke(app, ["train", "recalibrate", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "not enough new reviews" in result.output


@pytest.mark.parametrize(
    ("args", "says"),
    [
        (["triage", "/no/such/file.log"], "does not exist"),
        (["triage", "--scenario", "no.such"], "unknown scenario"),
        (["eval", "run", "--suite", "bogus"], "unknown suite"),
        (["providers", "check", "bogus"], "unknown provider"),
        (["data", "download", "--source", "nope"], "unknown source"),
    ],
)
def test_mistakes_get_a_clear_message_not_a_traceback(args: list[str], says: str) -> None:
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert says in " ".join(result.output.split())  # rich wraps long messages
    assert "Traceback" not in result.output


@pytest.mark.parametrize("name", ["gemini", "nim-local", "azure"])
def test_listing_models_of_a_provider_not_set_up_says_so(name: str) -> None:
    """It sent a keyless request (a 404 traceback) or failed on a missing URL (ValueError)."""
    result = CliRunner().invoke(app, ["providers", "models", name])
    assert result.exit_code == 1
    assert f"{name} is not set up" in " ".join(result.output.split())
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_triage_asks_for_the_database_to_be_set_up_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logs = tmp_path / "app.log"
    logs.write_text("2026-10-29T10:00:00Z ERROR app: disk full\n", encoding="utf-8")
    monkeypatch.setenv("ARIA_DATABASE_URL", f"sqlite:///{tmp_path / 'fresh.db'}")
    reset_caches()
    result = CliRunner().invoke(app, ["triage", str(logs)])
    assert result.exit_code == 1
    assert "aria db upgrade" in result.output


def test_serve_asks_for_the_database_to_be_set_up_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARIA_DATABASE_URL", f"sqlite:///{tmp_path / 'fresh.db'}")
    reset_caches()
    result = CliRunner().invoke(app, ["serve"])
    assert result.exit_code == 1
    assert "aria db upgrade" in result.output
    assert "Traceback" not in result.output


def test_training_will_not_replace_the_committed_model_with_one_fit_on_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path))  # no data/raw/loghub-2k here
    reset_caches()
    model = Path("models/severity_log.json")
    before = model.read_bytes()
    result = CliRunner().invoke(app, ["train", "severity"])
    assert result.exit_code == 1
    assert "--fixtures" in " ".join(result.output.split())
    assert "Traceback" not in result.output
    assert model.read_bytes() == before


def test_a_system_name_with_path_characters_gets_a_clear_message(tmp_path: Path) -> None:
    logs = tmp_path / "app.log"
    logs.write_text("2026-10-29T10:00:00Z ERROR app: disk full\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["triage", str(logs), "--system", "../etc"])
    assert result.exit_code == 2
    assert "letters, digits" in " ".join(result.output.split())
    assert "Traceback" not in result.output


def test_checking_an_unconfigured_provider_by_name_fails() -> None:
    runner = CliRunner()
    named = runner.invoke(app, ["providers", "check", "azure", "--no-probe"])
    assert named.exit_code == 1, named.output
    assert "disabled" in named.output
    # Without a name, providers nobody configured are not failures: offline is a valid setup.
    every = runner.invoke(app, ["providers", "check", "--no-probe"])
    assert every.exit_code == 0, every.output
