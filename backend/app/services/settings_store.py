"""Typed access to the `settings` key/value table with env-var precedence.

Env precedence (architecture.md): QBIT_URL / QBIT_USERNAME / QBIT_PASSWORD, APP_PASSWORD, ALLOW_PRIVATE_FEED_HOSTS
override DB values when set; such fields report `source: "env"` and PUTs ignore them with a warning.
Functions flush but never commit; callers own the transaction.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SettingKV
from app.schemas import AppSettingsIn, AppSettingsOut, QbitConfigIn, QbitConfigOut, QbitTestIn, QbitTestResultOut
from app.services import crypto
from app.services.paths import DEFAULT_MEDIA_BASE, DEFAULT_SEASON_FOLDER_FORMAT

# Keys
MEDIA_BASE_PATH = "media_base_path"
DEFAULT_SEASON_FOLDER_FORMAT_KEY = "default_season_folder_format"
DUPLICATE_POLICY = "duplicate_policy"
ALLOW_PRIVATE_FEED_HOSTS = "allow_private_feed_hosts"
FEED_FETCH_TIMEOUT_SECONDS = "feed_fetch_timeout_seconds"
LOG_RETENTION_DAYS = "log_retention_days"
AUTH_PASSWORD_HASH = "auth_password_hash"
QBIT_URL = "qbit_url"
QBIT_USERNAME = "qbit_username"
QBIT_PASSWORD_ENC = "qbit_password_enc"
QBIT_CATEGORY = "qbit_category"
QBIT_TIMEOUT_SECONDS = "qbit_timeout_seconds"
QBIT_START_IMMEDIATELY = "qbit_start_immediately"
QBIT_POLL_STATUS = "qbit_poll_status"
QBIT_LAST_TEST_JSON = "qbit_last_test_json"
DEMO_SEEDED = "demo_seeded"  # legacy key (old demo seed); kept so existing DBs stay readable
FEED_SEEDED = "feed_seeded"
ANIMETOSHO_TEMPLATE_BACKFILLED = "animetosho_template_backfilled"
AUTO_SEARCH_MISSING = "auto_search_missing"
SEARCH_INTERVAL_HOURS = "search_interval_hours"
METADATA_REFRESH_HOURS = "metadata_refresh_hours"
SEARCH_DELAY_SECONDS = "search_delay_seconds"
TMDB_API_KEY = "tmdb_api_key"  # Fernet-encrypted

DEFAULTS: dict[str, Any] = {
    MEDIA_BASE_PATH: DEFAULT_MEDIA_BASE,
    DEFAULT_SEASON_FOLDER_FORMAT_KEY: DEFAULT_SEASON_FOLDER_FORMAT,
    DUPLICATE_POLICY: "one_per_episode",
    ALLOW_PRIVATE_FEED_HOSTS: False,
    FEED_FETCH_TIMEOUT_SECONDS: 20,
    LOG_RETENTION_DAYS: 30,
    QBIT_URL: "",
    QBIT_USERNAME: "",
    QBIT_CATEGORY: None,
    QBIT_TIMEOUT_SECONDS: 15,
    QBIT_START_IMMEDIATELY: True,
    QBIT_POLL_STATUS: True,
    AUTO_SEARCH_MISSING: False,
    SEARCH_INTERVAL_HOURS: 24,
    METADATA_REFRESH_HOURS: 12,
    SEARCH_DELAY_SECONDS: 3,
}

_MISSING: Any = object()


def get(db: Session, key: str, default: Any = _MISSING) -> Any:
    """Stored value for `key`; else `default`; else DEFAULTS[key] (or None)."""
    row = db.get(SettingKV, key)
    if row is not None:
        return row.value
    if default is not _MISSING:
        return default
    return DEFAULTS.get(key)


def set(db: Session, key: str, value: Any) -> None:
    row = db.get(SettingKV, key)
    if row is None:
        db.add(SettingKV(key=key, value=value))
    else:
        row.value = value
        row.updated_at = datetime.now(UTC)
    db.flush()


def delete(db: Session, key: str) -> None:
    row = db.get(SettingKV, key)
    if row is not None:
        db.delete(row)
        db.flush()


def get_many(db: Session, keys: builtins.list[str]) -> dict[str, Any]:
    rows = {r.key: r.value for r in db.scalars(select(SettingKV).where(SettingKV.key.in_(keys)))}
    return {k: rows[k] if k in rows else DEFAULTS.get(k) for k in keys}


def ensure_defaults(db: Session) -> None:
    """Write DEFAULTS for keys that are absent (idempotent)."""
    existing = builtins.set(db.scalars(select(SettingKV.key)))
    for key, value in DEFAULTS.items():
        if key not in existing:
            db.add(SettingKV(key=key, value=value))
    db.flush()


# ---------------------------------------------------------------- app settings


def get_media_base_path(db: Session) -> str:
    return str(get(db, MEDIA_BASE_PATH))


def allow_private_feed_hosts(db: Session, settings: Settings) -> bool:
    if settings.ALLOW_PRIVATE_FEED_HOSTS is not None:
        return settings.ALLOW_PRIVATE_FEED_HOSTS
    return bool(get(db, ALLOW_PRIVATE_FEED_HOSTS))


def get_int(db: Session, key: str, minimum: int = 0) -> int:
    """Integer setting with a fallback to DEFAULTS when the stored value is unusable."""
    try:
        value = int(get(db, key))
    except (TypeError, ValueError):
        value = int(DEFAULTS[key])
    return max(minimum, value)


def get_tmdb_api_key(db: Session, settings: Settings) -> str:
    """Effective TMDB key (env `TMDB_API_KEY` wins); "" when not configured. Never log the result."""
    if settings.TMDB_API_KEY is not None:
        return settings.TMDB_API_KEY.strip()
    enc = get(db, TMDB_API_KEY, None)
    if not enc:
        return ""
    try:
        return crypto.decrypt(str(enc), settings)
    except crypto.CryptoError:
        return ""


def get_app_settings(db: Session, settings: Settings) -> AppSettingsOut:
    v = get_many(
        db,
        [
            MEDIA_BASE_PATH,
            DEFAULT_SEASON_FOLDER_FORMAT_KEY,
            DUPLICATE_POLICY,
            FEED_FETCH_TIMEOUT_SECONDS,
            LOG_RETENTION_DAYS,
            AUTO_SEARCH_MISSING,
            SEARCH_INTERVAL_HOURS,
            METADATA_REFRESH_HOURS,
            SEARCH_DELAY_SECONDS,
        ],
    )
    sources: dict[str, str] = {k: "db" for k in (*v.keys(), ALLOW_PRIVATE_FEED_HOSTS, TMDB_API_KEY)}
    if settings.ALLOW_PRIVATE_FEED_HOSTS is not None:
        sources[ALLOW_PRIVATE_FEED_HOSTS] = "env"
    if settings.TMDB_API_KEY is not None:
        sources[TMDB_API_KEY] = "env"
    return AppSettingsOut(
        media_base_path=v[MEDIA_BASE_PATH],
        default_season_folder_format=v[DEFAULT_SEASON_FOLDER_FORMAT_KEY],
        duplicate_policy=v[DUPLICATE_POLICY],
        allow_private_feed_hosts=allow_private_feed_hosts(db, settings),
        feed_fetch_timeout_seconds=int(v[FEED_FETCH_TIMEOUT_SECONDS]),
        log_retention_days=int(v[LOG_RETENTION_DAYS]),
        auto_search_missing=bool(v[AUTO_SEARCH_MISSING]),
        search_interval_hours=get_int(db, SEARCH_INTERVAL_HOURS, 1),
        metadata_refresh_hours=get_int(db, METADATA_REFRESH_HOURS, 1),
        search_delay_seconds=get_int(db, SEARCH_DELAY_SECONDS, 0),
        tmdb_api_key_set=bool(get_tmdb_api_key(db, settings)),
        sources=sources,  # type: ignore[arg-type]
    )


def set_app_settings(db: Session, settings: Settings, data: AppSettingsIn) -> AppSettingsOut:
    """Persist `schemas.AppSettingsIn`; env-overridden fields are ignored with a warning. Returns AppSettingsOut."""
    warnings: builtins.list[str] = []
    set(db, MEDIA_BASE_PATH, data.media_base_path)
    set(db, DEFAULT_SEASON_FOLDER_FORMAT_KEY, data.default_season_folder_format)
    set(db, DUPLICATE_POLICY, data.duplicate_policy)
    set(db, FEED_FETCH_TIMEOUT_SECONDS, data.feed_fetch_timeout_seconds)
    set(db, LOG_RETENTION_DAYS, data.log_retention_days)
    sent = data.model_fields_set
    for key in (AUTO_SEARCH_MISSING, SEARCH_INTERVAL_HOURS, METADATA_REFRESH_HOURS, SEARCH_DELAY_SECONDS):
        if key in sent:
            set(db, key, getattr(data, key))
    if data.tmdb_api_key is not None:
        if settings.TMDB_API_KEY is not None:
            warnings.append("tmdb_api_key is set by environment variable TMDB_API_KEY; ignored")
        elif data.tmdb_api_key.strip() == "":
            delete(db, TMDB_API_KEY)
        else:
            set(db, TMDB_API_KEY, crypto.encrypt(data.tmdb_api_key.strip(), settings))
    if settings.ALLOW_PRIVATE_FEED_HOSTS is not None:
        if data.allow_private_feed_hosts != settings.ALLOW_PRIVATE_FEED_HOSTS:
            warnings.append("allow_private_feed_hosts is set by environment variable ALLOW_PRIVATE_FEED_HOSTS; ignored")
    else:
        set(db, ALLOW_PRIVATE_FEED_HOSTS, bool(data.allow_private_feed_hosts))
    out = get_app_settings(db, settings)
    out.warnings = warnings
    return out


# ---------------------------------------------------------------- qBittorrent


@dataclass(frozen=True)
class QbitCredentials:
    """Effective qBittorrent connection settings for services (contains the plaintext password; never log)."""

    url: str
    username: str
    password: str
    category: str | None
    timeout_seconds: int
    start_immediately: bool
    poll_status: bool

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def __repr__(self) -> str:  # keep the password out of reprs/logs
        return f"QbitCredentials(url={self.url!r}, username={self.username!r}, password=***)"


def _stored_password(db: Session, settings: Settings) -> str:
    enc = get(db, QBIT_PASSWORD_ENC, None)
    if not enc:
        return ""
    return crypto.decrypt(str(enc), settings)


def get_qbit_credentials(db: Session, settings: Settings) -> QbitCredentials:
    v = get_many(
        db,
        [QBIT_URL, QBIT_USERNAME, QBIT_CATEGORY, QBIT_TIMEOUT_SECONDS, QBIT_START_IMMEDIATELY, QBIT_POLL_STATUS],
    )
    password = settings.QBIT_PASSWORD if settings.QBIT_PASSWORD is not None else _stored_password(db, settings)
    return QbitCredentials(
        url=(settings.QBIT_URL or v[QBIT_URL] or "").rstrip("/"),
        username=settings.QBIT_USERNAME if settings.QBIT_USERNAME is not None else (v[QBIT_USERNAME] or ""),
        password=password,
        category=v[QBIT_CATEGORY] or None,
        timeout_seconds=int(v[QBIT_TIMEOUT_SECONDS]),
        start_immediately=bool(v[QBIT_START_IMMEDIATELY]),
        poll_status=bool(v[QBIT_POLL_STATUS]),
    )


def get_qbit_last_test(db: Session) -> QbitTestResultOut | None:
    raw = get(db, QBIT_LAST_TEST_JSON, None)
    if not raw:
        return None
    try:
        return QbitTestResultOut.model_validate(raw)
    except ValueError:
        return None


def set_qbit_last_test(db: Session, result: QbitTestResultOut) -> None:
    set(db, QBIT_LAST_TEST_JSON, result.model_dump(mode="json"))


def get_qbit_config(db: Session, settings: Settings) -> QbitConfigOut:
    """Never contains the password."""
    v = get_many(
        db,
        [QBIT_URL, QBIT_USERNAME, QBIT_CATEGORY, QBIT_TIMEOUT_SECONDS, QBIT_START_IMMEDIATELY, QBIT_POLL_STATUS],
    )
    sources = {
        "url": "env" if settings.QBIT_URL else "db",
        "username": "env" if settings.QBIT_USERNAME is not None else "db",
        "password": "env" if settings.QBIT_PASSWORD is not None else "db",
        "category": "db",
        "timeout_seconds": "db",
        "start_immediately": "db",
        "poll_status": "db",
    }
    password_set = settings.QBIT_PASSWORD is not None or bool(get(db, QBIT_PASSWORD_ENC, None))
    return QbitConfigOut(
        url=(settings.QBIT_URL or v[QBIT_URL] or ""),
        username=settings.QBIT_USERNAME if settings.QBIT_USERNAME is not None else (v[QBIT_USERNAME] or ""),
        password_set=password_set,
        category=v[QBIT_CATEGORY] or None,
        timeout_seconds=int(v[QBIT_TIMEOUT_SECONDS]),
        start_immediately=bool(v[QBIT_START_IMMEDIATELY]),
        poll_status=bool(v[QBIT_POLL_STATUS]),
        sources=sources,  # type: ignore[arg-type]
        last_test=get_qbit_last_test(db),
    )


def set_qbit_config(db: Session, settings: Settings, data: QbitConfigIn) -> QbitConfigOut:
    """Persist `schemas.QbitConfigIn`. password None = unchanged, "" = clear. Returns QbitConfigOut with warnings."""
    warnings: builtins.list[str] = []
    if settings.QBIT_URL:
        if data.url and data.url != settings.QBIT_URL.rstrip("/"):
            warnings.append("url is set by environment variable QBIT_URL; ignored")
    else:
        set(db, QBIT_URL, data.url)
    if settings.QBIT_USERNAME is not None:
        if data.username and data.username != settings.QBIT_USERNAME:
            warnings.append("username is set by environment variable QBIT_USERNAME; ignored")
    else:
        set(db, QBIT_USERNAME, data.username)
    if data.password is not None:
        if settings.QBIT_PASSWORD is not None:
            warnings.append("password is set by environment variable QBIT_PASSWORD; ignored")
        elif data.password == "":
            delete(db, QBIT_PASSWORD_ENC)
        else:
            set(db, QBIT_PASSWORD_ENC, crypto.encrypt(data.password, settings))
    set(db, QBIT_CATEGORY, data.category)
    set(db, QBIT_TIMEOUT_SECONDS, data.timeout_seconds)
    set(db, QBIT_START_IMMEDIATELY, data.start_immediately)
    set(db, QBIT_POLL_STATUS, data.poll_status)
    out = get_qbit_config(db, settings)
    out.warnings = warnings
    return out


def merge_qbit_test_input(db: Session, settings: Settings, data: QbitTestIn | None) -> QbitCredentials:
    """Effective credentials for POST /api/qbit/test: stored/env values overlaid with any non-None fields of
    `schemas.QbitTestIn` (password omitted = use stored)."""
    base = get_qbit_credentials(db, settings)
    if data is None:
        return base
    return QbitCredentials(
        url=(data.url.rstrip("/") if data.url else base.url),
        username=data.username if data.username is not None else base.username,
        password=data.password if data.password is not None else base.password,
        category=(data.category or None) if data.category is not None else base.category,
        timeout_seconds=data.timeout_seconds if data.timeout_seconds is not None else base.timeout_seconds,
        start_immediately=data.start_immediately if data.start_immediately is not None else base.start_immediately,
        poll_status=data.poll_status if data.poll_status is not None else base.poll_status,
    )
