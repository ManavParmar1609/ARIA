"""Alembic environment. Batch mode keeps ALTER TABLE working on SQLite."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from aria.db.engine import make_engine
from aria.db.models import Base

target_metadata = Base.metadata
config = context.config


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        return
    url = config.get_main_option("sqlalchemy.url") or ""
    engine = make_engine(url, auth=config.attributes.get("auth", "default"))
    with engine.connect() as conn:
        _configure(conn)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
