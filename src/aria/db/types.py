"""Column types that behave the same on SQLite and SQL Server."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Stores naive UTC and always returns timezone-aware UTC datetimes.

    SQLite has no time zones and SQL Server's DATETIME2 drops them, so normalising at the
    boundary avoids mixing naive and aware values in application code.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:  # noqa: ARG002
        if value is None:
            return None
        if not isinstance(value, datetime):
            msg = f"expected datetime, got {type(value).__name__}"
            raise TypeError(msg)
        utc: datetime = value.astimezone(UTC) if value.tzinfo is not None else value
        return utc.replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:  # noqa: ARG002
        if value is None:
            return None
        if isinstance(value, str):  # some SQLite drivers hand back ISO strings
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime):
            msg = f"expected datetime from database, got {type(value).__name__}"
            raise TypeError(msg)
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
