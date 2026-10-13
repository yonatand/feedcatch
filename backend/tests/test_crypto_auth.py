from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterator

import pytest
import structlog
from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.config import Settings
from app.logging_setup import REDACTED, configure_logging, redact_processor
from app.services import auth, crypto, settings_store

# ---------------------------------------------------------------- crypto


def test_file_key_created_and_reused(settings: Settings) -> None:
    token = crypto.encrypt("hunter2-fake", settings)
    key_path = settings.data_dir / crypto.SECRET_FILE_NAME
    assert key_path.exists()
    if sys.platform != "win32":
        assert (os.stat(key_path).st_mode & 0o777) == 0o600
    assert token != "hunter2-fake"
    assert crypto.decrypt(token, settings) == "hunter2-fake"
    key_before = key_path.read_bytes()
    crypto.encrypt("x", settings)
    assert key_path.read_bytes() == key_before


def test_env_secret_key(tmp_path: object, settings: Settings) -> None:
    s1 = Settings(APP_DATA_DIR=settings.APP_DATA_DIR, APP_SECRET_KEY="some raw passphrase")
    s2 = Settings(APP_DATA_DIR=settings.APP_DATA_DIR, APP_SECRET_KEY="another passphrase")
    token = crypto.encrypt("pw", s1)
    assert crypto.decrypt(token, s1) == "pw"
    assert not (settings.data_dir / crypto.SECRET_FILE_NAME).exists()
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(token, s2)


# ---------------------------------------------------------------- auth


def test_hash_and_verify() -> None:
    h = auth.hash_password("correct horse")
    assert h != "correct horse"
    assert auth.verify_password("correct horse", h)
    assert not auth.verify_password("wrong", h)
    assert not auth.verify_password("x", "not-a-hash")


def test_session_token_roundtrip(settings: Settings) -> None:
    ser = auth.get_serializer(settings)
    token = auth.create_session_token(ser)
    assert auth.read_session_token(ser, token)
    assert not auth.read_session_token(ser, token + "x")
    assert not auth.read_session_token(ser, None)
    assert not auth.read_session_token(ser, token, max_age=-1)
    other = auth.get_serializer(Settings(APP_DATA_DIR=settings.APP_DATA_DIR, APP_SECRET_KEY="different"))
    assert not auth.read_session_token(other, token)


def _request(cookie: str | None = None) -> Request:
    headers = [(b"cookie", f"{auth.SESSION_COOKIE}={cookie}".encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": "/api/x", "headers": headers})


def test_require_auth(settings: Settings) -> None:
    with pytest.raises(HTTPException) as exc:
        auth.require_auth(_request(), settings)
    assert exc.value.status_code == 401 and exc.value.detail == "unauthenticated"
    token = auth.create_session_token(auth.get_serializer(settings))
    auth.require_auth(_request(token), settings)  # no raise
    disabled = Settings(APP_DATA_DIR=settings.APP_DATA_DIR, APP_AUTH_DISABLED=True)
    auth.require_auth(_request(), disabled)


def test_auth_status_and_login(db: Session, settings: Settings) -> None:
    assert auth.auth_status(db, settings) == ("password", True)
    assert not auth.check_login_password(db, settings, "whatever1")
    auth.setup_password(db, "s3cret-pass")
    assert auth.auth_status(db, settings) == ("password", False)
    assert auth.check_login_password(db, settings, "s3cret-pass")
    assert not auth.check_login_password(db, settings, "nope-nope")
    stored = settings_store.get(db, settings_store.AUTH_PASSWORD_HASH)
    assert stored and "s3cret-pass" not in stored

    env = Settings(APP_DATA_DIR=settings.APP_DATA_DIR, APP_PASSWORD="env-password")
    assert auth.auth_status(db, env) == ("password", False)
    assert auth.check_login_password(db, env, "env-password")
    assert not auth.check_login_password(db, env, "s3cret-pass")

    disabled = Settings(APP_DATA_DIR=settings.APP_DATA_DIR, APP_AUTH_DISABLED=True)
    assert auth.auth_status(db, disabled) == ("disabled", False)


def test_rate_limiter() -> None:
    rl = auth.LoginRateLimiter(max_failures=5, window_seconds=60)
    for i in range(4):
        rl.record_failure("1.2.3.4", now=100.0 + i)
        assert not rl.is_blocked("1.2.3.4", now=100.0 + i)
    rl.record_failure("1.2.3.4", now=104.0)
    assert rl.is_blocked("1.2.3.4", now=105.0)
    assert not rl.is_blocked("5.6.7.8", now=105.0)
    assert not rl.is_blocked("1.2.3.4", now=165.0)  # window slid past the first failure
    rl.record_failure("1.2.3.4", now=170.0)
    rl.reset("1.2.3.4")
    assert not rl.is_blocked("1.2.3.4", now=170.0)


# ---------------------------------------------------------------- logging redaction


def test_redact_processor_recursive() -> None:
    ev = {
        "event": "qbit_login",
        "password": "fake-pw",
        "QBIT_PASSWORD": "fake",
        "Authorization": "Bearer x",
        "nested": {"api_token": "t", "ok": 1, "items": [{"Cookie": "SID=abc"}, {"name": "x"}]},
        "url": "http://host:8080",
    }
    out = redact_processor(None, "info", ev)
    assert out["event"] == "qbit_login"
    assert out["password"] == REDACTED
    assert out["QBIT_PASSWORD"] == REDACTED
    assert out["Authorization"] == REDACTED
    assert out["nested"]["api_token"] == REDACTED
    assert out["nested"]["ok"] == 1
    assert out["nested"]["items"][0]["Cookie"] == REDACTED
    assert out["nested"]["items"][1]["name"] == "x"
    assert out["url"] == "http://host:8080"


@pytest.fixture
def _restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers = handlers
    root.setLevel(level)
    structlog.reset_defaults()


@pytest.mark.usefixtures("_restore_logging")
def test_configure_logging_json_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    structlog.get_logger("t").info("login_attempt", secret_key="fake-secret", details={"session_cookie": "c"}, n=1)
    structlog.get_logger("t").debug("hidden")
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "login_attempt"
    assert rec["secret_key"] == REDACTED
    assert rec["details"]["session_cookie"] == REDACTED
    assert rec["n"] == 1
    assert "fake-secret" not in lines[0]
