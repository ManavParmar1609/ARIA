"""Shared fixtures.

Every test runs offline: provider credentials are removed from the environment so fallback
chains always end at the deterministic fake provider, and the database is a fresh SQLite file.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from aria.config import reset_caches

REPO_ROOT = Path(__file__).resolve().parents[1]
_PROVIDER_ENV = (
    "NVIDIA_API_KEY",
    "NVIDIA_NIM_BASE_URL",
    "NIM_LOCAL_BASE_URL",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "SLACK_WEBHOOK_URL",
    "TEAMS_WEBHOOK_URL",
    "ARIA_OUTBOUND_WEBHOOK_URL",
    "ARIA_API_KEYS",
)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARIA_ENV", "test")
    monkeypatch.setenv("ARIA_DATABASE_URL", f"sqlite:///{tmp_path / 'aria.db'}")
    monkeypatch.setenv("ARIA_CONFIG_FILE", str(REPO_ROOT / "config" / "aria.yaml"))
    monkeypatch.chdir(REPO_ROOT)
    reset_caches()
    yield
    reset_caches()
