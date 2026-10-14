"""Application settings from environment variables (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-level configuration. DB-stored settings live in `services.settings_store`."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=True)

    APP_DATA_DIR: str = "./.data"
    APP_SECRET_KEY: str | None = None
    APP_PASSWORD: str | None = None
    APP_AUTH_DISABLED: bool = False
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_LOG_LEVEL: str = "INFO"
    QBIT_URL: str | None = None
    QBIT_USERNAME: str | None = None
    QBIT_PASSWORD: str | None = None
    FEED_URL: str | None = None
    TMDB_API_KEY: str | None = None
    # Jikan (MyAnimeList mirror) is a best-effort episode-title fallback for AniList; disable on networks that block it.
    JIKAN_ENABLED: bool = True
    ALLOW_PRIVATE_FEED_HOSTS: bool | None = None
    # Set false to run the API without background jobs (tests, one-off inspection).
    APP_SCHEDULER_ENABLED: bool = True

    @field_validator(
        "APP_SECRET_KEY",
        "APP_PASSWORD",
        "QBIT_URL",
        "QBIT_USERNAME",
        "QBIT_PASSWORD",
        "FEED_URL",
        "TMDB_API_KEY",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        # `.env.example` ships empty values; treat "" as "not set" so DB values apply.
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("ALLOW_PRIVATE_FEED_HOSTS", mode="before")
    @classmethod
    def _empty_bool_to_none(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @property
    def data_dir(self) -> Path:
        return Path(self.APP_DATA_DIR)

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    def ensure_data_dir(self) -> Path:
        """Create the app's own data dir (never the media dir)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_data_dir()
    return settings
