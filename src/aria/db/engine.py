"""Engine and session management.

SQLite runs in WAL mode so the API, the worker and SSE readers can share one file. For Azure SQL
set ``ARIA_DATABASE_AUTH=entra`` (with the ``azure`` extra installed) and every new connection
receives a Microsoft Entra ID access token from ``DefaultAzureCredential``, so no password is
stored anywhere. Managed identity works the same way inside Azure.
"""

from __future__ import annotations

import struct
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from aria.config import get_settings

_SQL_COPT_SS_ACCESS_TOKEN = 1256  # ODBC attribute for an Entra ID access token
_AZURE_SQL_SCOPE = "https://database.windows.net/.default"

_engines: dict[str, Engine] = {}
_lock = threading.Lock()


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.close()


def _mssql_fast_executemany(
    _conn: Any, cursor: Any, _statement: str, _params: Any, _context: Any, executemany: bool
) -> None:
    if executemany:
        cursor.fast_executemany = True


def _attach_entra_token(engine: Engine) -> None:
    """Inject a fresh Entra ID token on every new pyodbc connection."""
    from azure.identity import DefaultAzureCredential  # noqa: PLC0415 - optional extra

    credential = DefaultAzureCredential()

    @event.listens_for(engine, "do_connect")
    def _provide_token(_dialect: Any, _rec: Any, cargs: list[Any], cparams: dict[str, Any]) -> None:
        # A URL without a user makes SQLAlchemy ask for Windows auth, which the driver refuses to
        # combine with an access token; drop it (the recipe in SQLAlchemy's mssql docs).
        if cargs and isinstance(cargs[0], str):
            cargs[0] = cargs[0].replace(";Trusted_Connection=Yes", "")
        token = credential.get_token(_AZURE_SQL_SCOPE).token.encode("utf-16-le")
        cparams["attrs_before"] = {
            _SQL_COPT_SS_ACCESS_TOKEN: struct.pack(f"<I{len(token)}s", len(token), token)
        }


def make_engine(url: str, *, auth: str = "default", echo: bool = False) -> Engine:
    parsed = make_url(url)
    backend = parsed.get_backend_name()
    if backend == "sqlite":
        database = parsed.database
        if database and database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            url, echo=echo, connect_args={"check_same_thread": False, "timeout": 30}
        )
        event.listen(engine, "connect", _sqlite_pragmas)
        return engine

    engine = create_engine(
        url, echo=echo, pool_pre_ping=True, pool_recycle=1800, pool_size=10, max_overflow=10
    )
    if backend == "mssql":
        event.listen(engine, "before_cursor_execute", _mssql_fast_executemany)
        if auth == "entra":
            _attach_entra_token(engine)
    return engine


def get_engine() -> Engine:
    settings = get_settings()
    key = f"{settings.database_auth}|{settings.database_url}"
    with _lock:
        engine = _engines.get(key)
        if engine is None:
            engine = make_engine(settings.database_url, auth=settings.database_auth)
            _engines[key] = engine
        return engine


def dispose_engines() -> None:
    """Close every pooled connection (worker shutdown and tests)."""
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()


def session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """A transactional scope: commit on success, roll back on any error."""
    session = session_factory(engine)()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> None:
    """Create tables directly. Deployments use Alembic (`aria db upgrade`); tests use this."""
    from aria.db.models import Base  # noqa: PLC0415 - keeps model import out of engine setup

    Base.metadata.create_all(engine or get_engine())
