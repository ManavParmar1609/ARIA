"""Structured logging with secret scrubbing.

Every log record passes through ``scrub_secrets`` so that keys, tokens and passwords never reach
log storage, even when a caller logs a whole request or config object by mistake.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|authorization|password|secret|token|cookie)", re.IGNORECASE
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._\-]{8,}|nvapi-[a-z0-9_\-]{8,}|sk-[a-z0-9_\-]{16,}|eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]+)"
)
REDACTED = "[redacted]"


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _SENSITIVE_VALUE.sub(REDACTED, value)
    if isinstance(value, dict):
        return {
            key: REDACTED if _SENSITIVE_KEY.search(str(key)) else _scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(_scrub(item) for item in value)
    return value


def scrub_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor that masks sensitive keys and token-shaped values."""
    for key in list(event_dict):
        if _SENSITIVE_KEY.search(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _scrub(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    """Configure structlog and the standard library to emit one consistent stream."""
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        scrub_secrets,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
