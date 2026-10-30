"""Programmatic Alembic entry points used by the CLI and the container start-up."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from aria.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(url: str | None = None) -> Config:
    settings = get_settings()
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # ConfigParser treats % as interpolation; escape it in passwords and query strings.
    cfg.set_main_option("sqlalchemy.url", (url or settings.database_url).replace("%", "%%"))
    cfg.attributes["auth"] = settings.database_auth
    return cfg


def upgrade(revision: str = "head", url: str | None = None) -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(revision: str, url: str | None = None) -> None:
    command.downgrade(alembic_config(url), revision)


def new_revision(message: str, url: str | None = None) -> None:
    command.revision(alembic_config(url), message=message, autogenerate=True)


def current(url: str | None = None) -> None:
    command.current(alembic_config(url), verbose=True)
