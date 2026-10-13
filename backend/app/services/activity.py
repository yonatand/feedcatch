"""Activity log (persisted, shown in the UI) + mirrored structlog line."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

import structlog
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.logging_setup import _redact_value
from app.models import ActivityLog, utcnow

ActivityLevel = Literal["info", "warning", "error"]

log = structlog.get_logger("activity")


def log_event(
    db: Session,
    level: ActivityLevel,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
    entry_id: int | None = None,
    download_id: int | None = None,
) -> ActivityLog:
    """Add an ActivityLog row (flushed, not committed) and emit a structlog line. Details are redacted."""
    safe_details = _redact_value(details) if details is not None else None
    row = ActivityLog(
        ts=utcnow(),
        level=level,
        event_type=event_type,
        message=message,
        details=safe_details,
        entry_id=entry_id,
        download_id=download_id,
    )
    db.add(row)
    db.flush()
    emit = {"info": log.info, "warning": log.warning, "error": log.error}.get(level, log.info)
    emit(event_type, message=message, details=safe_details, entry_id=entry_id, download_id=download_id)
    return row


def purge_older_than(db: Session, days: int) -> int:
    """Delete activity rows older than `days`; returns the number deleted (flush only)."""
    cutoff = utcnow() - timedelta(days=days)
    result = db.execute(delete(ActivityLog).where(ActivityLog.ts < cutoff))
    db.flush()
    return int(getattr(result, "rowcount", 0) or 0)
