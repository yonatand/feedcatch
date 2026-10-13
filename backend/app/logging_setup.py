"""structlog JSON logging with secret redaction (safety invariant 4)."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

REDACTED = "***"
SENSITIVE_KEY_RE = re.compile(r"pass|secret|token|cookie|authorization", re.IGNORECASE)
_NEVER_REDACT = {"event", "level", "timestamp", "logger"}


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (REDACTED if _is_sensitive(k) else _redact_value(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(v) for v in value)
    return value


def _is_sensitive(key: object) -> bool:
    return isinstance(key, str) and bool(SENSITIVE_KEY_RE.search(key))


def redact_processor(_logger: Any, _method: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Mask values of sensitive keys, recursively in dicts/lists."""
    for key in list(event_dict.keys()):
        if key in _NEVER_REDACT:
            continue
        if _is_sensitive(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog (JSON to stdout) and route stdlib logging through the same renderer."""
    lvl = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_processor,
    ]
    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(lvl),
        logger_factory=structlog.PrintLoggerFactory(),  # resolves sys.stdout per logger
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[structlog.stdlib.add_logger_name, *shared],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(lvl)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "apscheduler", "alembic"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    logging.getLogger("httpx").setLevel(max(lvl, logging.WARNING))


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
