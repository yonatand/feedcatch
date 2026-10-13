"""Password auth, signed session cookie, FastAPI dependency and login rate limiter."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import deque
from typing import Literal

import bcrypt
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services import settings_store
from app.services.crypto import get_key_material

SESSION_COOKIE = "feedcatch_session"
SESSION_MAX_AGE = 7 * 24 * 3600
_SESSION_SALT = "feedcatch-session-v1"

AuthMode = Literal["password", "disabled"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def get_serializer(settings: Settings | None = None) -> URLSafeTimedSerializer:
    s = settings or get_settings()
    secret = hashlib.sha256(b"session:" + get_key_material(s)).hexdigest()
    return URLSafeTimedSerializer(secret, salt=_SESSION_SALT)


def create_session_token(serializer: URLSafeTimedSerializer) -> str:
    return serializer.dumps({"v": 1, "iat": int(time.time())})


def read_session_token(serializer: URLSafeTimedSerializer, token: str | None, max_age: int = SESSION_MAX_AGE) -> bool:
    """True when `token` is a valid, unexpired session token."""
    if not token:
        return False
    try:
        data = serializer.loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return False
    return isinstance(data, dict) and data.get("v") == 1


def is_authenticated(request: Request, settings: Settings) -> bool:
    if settings.APP_AUTH_DISABLED:
        return True
    return read_session_token(get_serializer(settings), request.cookies.get(SESSION_COOKIE))


def require_auth(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """FastAPI dependency for every /api/* route except /api/auth/*. Raises 401 {detail: "unauthenticated"}."""
    if settings.APP_AUTH_DISABLED:
        return
    if not read_session_token(get_serializer(settings), request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="unauthenticated")


def auth_status(db: Session, settings: Settings) -> tuple[AuthMode, bool]:
    """Return (auth_mode, setup_required)."""
    if settings.APP_AUTH_DISABLED:
        return "disabled", False
    if settings.APP_PASSWORD:
        return "password", False
    return "password", not bool(settings_store.get(db, settings_store.AUTH_PASSWORD_HASH, None))


def check_login_password(db: Session, settings: Settings, password: str) -> bool:
    """Verify a login attempt against APP_PASSWORD env (precedence) or the stored bcrypt hash."""
    if settings.APP_PASSWORD:
        return hmac.compare_digest(password.encode("utf-8"), settings.APP_PASSWORD.encode("utf-8"))
    stored = settings_store.get(db, settings_store.AUTH_PASSWORD_HASH, None)
    return bool(stored) and verify_password(password, str(stored))


def setup_password(db: Session, password: str) -> None:
    """Store a bcrypt hash (first-run setup). Caller checks setup_required and commits."""
    settings_store.set(db, settings_store.AUTH_PASSWORD_HASH, hash_password(password))


class LoginRateLimiter:
    """In-memory sliding window: `max_failures` failures per `window_seconds` per key (IP). Thread-safe."""

    def __init__(self, max_failures: int = 5, window_seconds: float = 60.0) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures.setdefault(key, deque())
        while q and now - q[0] >= self.window_seconds:
            q.popleft()
        return q

    def is_blocked(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            return len(self._prune(key, now)) >= self.max_failures

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
