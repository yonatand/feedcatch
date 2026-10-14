"""Shared fixtures. `db` is a tmp-file SQLite DB created via the real Alembic migration."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import config
from app.config import Settings
from app.db import SessionLocal, configure_engine, run_migrations

_ENV_KEYS = (
    "APP_DATA_DIR",
    "APP_SECRET_KEY",
    "APP_PASSWORD",
    "APP_AUTH_DISABLED",
    "APP_LOG_LEVEL",
    "QBIT_URL",
    "QBIT_USERNAME",
    "QBIT_PASSWORD",
    "FEED_URL",
    "TMDB_API_KEY",
    "JIKAN_ENABLED",
    "ALLOW_PRIVATE_FEED_HOSTS",
    "APP_SCHEDULER_ENABLED",
)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Never let the developer's real env leak into tests; point the data dir at tmp."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_SCHEDULER_ENABLED", "false")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(APP_DATA_DIR=str(tmp_path / "data"))
    s.ensure_data_dir()
    return s


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


@pytest.fixture
def db(db_url: str) -> Iterator[Session]:
    run_migrations(db_url)
    engine = configure_engine(db_url)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------- integration fixtures

PUBLIC_TEST_IP = "93.184.216.34"
PRIVATE_TEST_IP = "10.0.0.5"


def fake_resolve(host: str, port: int) -> list[str]:
    """Test DNS: `internal*.example.test` / `localhost` are private, other `*.example.test` hosts are public."""
    host = host.lower()
    if host == "localhost" or host.startswith("internal"):
        return [PRIVATE_TEST_IP if host != "localhost" else "127.0.0.1"]
    if host.endswith(".example.test") or host == "example.test":
        return [PUBLIC_TEST_IP]
    raise OSError(f"test DNS: unknown host {host}")


@pytest.fixture(autouse=True)
def _no_real_network_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake DNS for SSRF checks and no sleeping in the dispatcher."""
    from app.services import dispatcher, ssrf
    from app.services.metadata import anilist

    anilist.reset_jikan_backoff()  # module-level Jikan backoff must not leak between tests

    monkeypatch.setattr(ssrf, "_resolve", fake_resolve)
    monkeypatch.setattr(dispatcher, "POST_ADD_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(dispatcher, "RESOLVE_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(dispatcher, "RESOLVE_POLL_SECONDS", 0.0)


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    """All httpx traffic must be mocked; unmatched requests raise."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """App with auth disabled and the scheduler off; DB lives in the tmp APP_DATA_DIR."""
    monkeypatch.setenv("APP_AUTH_DISABLED", "true")
    config.get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """App in password mode (no APP_PASSWORD: first-run setup required)."""
    monkeypatch.delenv("APP_AUTH_DISABLED", raising=False)
    config.get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
