"""SQLAlchemy engine/session management and programmatic Alembic migrations."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
ALEMBIC_DIR = BACKEND_ROOT / "alembic"


def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def make_engine(url: str) -> Engine:
    """Create an engine; SQLite engines get WAL/foreign_keys/busy_timeout PRAGMAs on every connection."""
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
        event.listen(engine, "connect", _set_sqlite_pragmas)
    else:  # pragma: no cover - Postgres later
        engine = create_engine(url, future=True, pool_pre_ping=True)
    return engine


SessionLocal: sessionmaker[Session] = sessionmaker(autoflush=False, expire_on_commit=False)
_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the process engine, creating it from settings on first use."""
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
        SessionLocal.configure(bind=_engine)
    return _engine


def configure_engine(url: str) -> Engine:
    """(Re)bind the global engine + SessionLocal to `url` (used by tests and app startup)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(url)
    SessionLocal.configure(bind=_engine)
    return _engine


# Backwards-friendly alias named in the task brief.
set_engine_for_tests = configure_engine


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session and always closes it."""
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations(engine_url: str | None = None) -> None:
    """Run `alembic upgrade head` programmatically against `engine_url` (default: settings DB)."""
    from alembic import command
    from alembic.config import Config

    url = engine_url or get_settings().database_url
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    # Tell env.py not to reconfigure logging (structlog owns it).
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
