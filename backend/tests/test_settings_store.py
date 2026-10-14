from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ActivityLog, FeedSource, Rule, Season, Series, SettingKV, utcnow
from app.schemas import AppSettingsIn, QbitConfigIn, QbitTestIn, RuleIn, SeriesIn
from app.services import activity, seed, settings_store


def test_get_set_defaults(db: Session) -> None:
    assert settings_store.get(db, "media_base_path") == "/home/qbittorrent-nox/media"
    assert settings_store.get(db, "unknown_key") is None
    assert settings_store.get(db, "unknown_key", 5) == 5
    settings_store.set(db, "log_retention_days", 7)
    settings_store.set(db, "log_retention_days", 9)
    assert settings_store.get(db, "log_retention_days") == 9
    assert settings_store.get_many(db, ["log_retention_days", "duplicate_policy"]) == {
        "log_retention_days": 9,
        "duplicate_policy": "one_per_episode",
    }


def test_app_settings_roundtrip_and_env(db: Session, settings: Settings) -> None:
    out = settings_store.get_app_settings(db, settings)
    assert out.media_base_path == "/home/qbittorrent-nox/media"
    assert out.sources["allow_private_feed_hosts"] == "db"
    new = AppSettingsIn(
        media_base_path="/srv/media/",
        default_season_folder_format="S{season:02d}",
        duplicate_policy="allow_upgrades",
        allow_private_feed_hosts=True,
        feed_fetch_timeout_seconds=30,
        log_retention_days=14,
    )
    out = settings_store.set_app_settings(db, settings, new)
    assert out.media_base_path == "/srv/media"
    assert out.allow_private_feed_hosts is True
    assert out.warnings == []

    env = Settings(APP_DATA_DIR=settings.APP_DATA_DIR, ALLOW_PRIVATE_FEED_HOSTS=False)
    out = settings_store.set_app_settings(db, env, new)
    assert out.allow_private_feed_hosts is False
    assert out.sources["allow_private_feed_hosts"] == "env"
    assert out.warnings and "ALLOW_PRIVATE_FEED_HOSTS" in out.warnings[0]
    assert settings_store.allow_private_feed_hosts(db, env) is False
    assert settings_store.allow_private_feed_hosts(db, settings) is True


@pytest.mark.parametrize("bad", ["relative", "/a/../b", "C:\\x"])
def test_app_settings_rejects_bad_base(bad: str) -> None:
    with pytest.raises(ValidationError):
        AppSettingsIn(media_base_path=bad)


def test_qbit_config_password_encrypted_never_returned(db: Session, settings: Settings) -> None:
    cfg = QbitConfigIn(
        url="http://host.docker.internal:8080/",
        username="admin",
        password="fake-password",
        category="anime",
        timeout_seconds=10,
        start_immediately=False,
        poll_status=True,
    )
    out = settings_store.set_qbit_config(db, settings, cfg)
    assert out.password_set is True
    assert out.url == "http://host.docker.internal:8080"
    assert "fake-password" not in out.model_dump_json()
    stored = settings_store.get(db, settings_store.QBIT_PASSWORD_ENC)
    assert stored and "fake-password" not in stored
    creds = settings_store.get_qbit_credentials(db, settings)
    assert creds.password == "fake-password"
    assert creds.category == "anime" and creds.start_immediately is False
    assert "fake-password" not in repr(creds)

    # omitted password = unchanged
    out = settings_store.set_qbit_config(db, settings, cfg.model_copy(update={"password": None}))
    assert settings_store.get_qbit_credentials(db, settings).password == "fake-password"
    # "" = clear
    out = settings_store.set_qbit_config(db, settings, cfg.model_copy(update={"password": ""}))
    assert out.password_set is False
    assert settings_store.get_qbit_credentials(db, settings).password == ""


def test_qbit_env_precedence(db: Session, settings: Settings) -> None:
    env = Settings(
        APP_DATA_DIR=settings.APP_DATA_DIR, QBIT_URL="http://qb:8080", QBIT_USERNAME="envuser", QBIT_PASSWORD="envpw"
    )
    out = settings_store.set_qbit_config(
        db, env, QbitConfigIn(url="http://other:1", username="dbuser", password="dbpw", category=None)
    )
    assert out.url == "http://qb:8080" and out.username == "envuser" and out.password_set
    assert out.sources["url"] == out.sources["username"] == out.sources["password"] == "env"
    assert len(out.warnings) == 3
    creds = settings_store.get_qbit_credentials(db, env)
    assert (creds.url, creds.username, creds.password) == ("http://qb:8080", "envuser", "envpw")
    merged = settings_store.merge_qbit_test_input(db, env, QbitTestIn(url="http://test:9"))
    assert merged.url == "http://test:9" and merged.password == "envpw"


def test_activity_log_and_purge(db: Session) -> None:
    row = activity.log_event(db, "info", "test_event", "hello", details={"password": "x", "n": 1})
    assert row.id is not None
    assert row.details == {"password": "***", "n": 1}
    old = activity.log_event(db, "warning", "old", "old event")
    old.ts = utcnow() - timedelta(days=40)
    db.flush()
    assert activity.purge_older_than(db, 30) == 1
    assert [r.event_type for r in db.scalars(select(ActivityLog))] == ["test_event"]


def test_seed_creates_nothing_without_feed_url(db: Session, settings: Settings) -> None:
    assert seed.seed_defaults(db, settings) is False
    assert seed.seed_defaults(db, settings) is False
    assert db.scalars(select(FeedSource)).all() == []
    assert db.scalars(select(Series)).all() == [] and db.scalars(select(Season)).all() == []
    assert db.scalars(select(Rule)).all() == []
    keys = set(db.scalars(select(SettingKV.key)))
    assert {"media_base_path", "qbit_timeout_seconds", "auto_search_missing", "search_interval_hours"} <= keys
    assert settings_store.get(db, settings_store.AUTO_SEARCH_MISSING) is False
    assert settings_store.get(db, settings_store.METADATA_REFRESH_HOURS) == 12
    assert settings_store.get(db, settings_store.SEARCH_DELAY_SECONDS) == 3


def test_seed_uses_feed_url_env_once(db: Session, settings: Settings) -> None:
    s = Settings(APP_DATA_DIR=settings.APP_DATA_DIR, FEED_URL="https://example.org/rss")
    assert seed.seed_defaults(db, s) is True
    feed = db.scalars(select(FeedSource)).one()
    assert (feed.name, feed.url, feed.search_url_template) == ("example.org", "https://example.org/rss", None)
    db.delete(feed)
    db.commit()
    assert seed.seed_defaults(db, s) is False  # created once only (a deleted feed stays deleted)
    assert db.scalars(select(FeedSource)).all() == []


def test_seed_animetosho_feed_gets_search_template(db: Session, settings: Settings) -> None:
    s = Settings(APP_DATA_DIR=settings.APP_DATA_DIR, FEED_URL="https://feed.animetosho.net/rss2")
    seed.seed_defaults(db, s)
    feed = db.scalars(select(FeedSource)).one()
    assert feed.name == "feed.animetosho.net"
    assert feed.search_url_template == "https://feed.animetosho.net/rss2?q={query}"
    assert seed.search_template_for("https://feed.animetosho.net/rss2?only_tor=1") == (
        "https://feed.animetosho.net/rss2?only_tor=1&q={query}"
    )
    assert seed.search_template_for("https://nyaa.si/?page=rss") is None


def test_seed_backfills_animetosho_template_once(db: Session, settings: Settings) -> None:
    feed = FeedSource(name="AnimeTosho", url="https://feed.animetosho.net/rss2")
    other = FeedSource(name="Other", url="https://feed.animetosho.net/rss2?filter=x")
    db.add_all([feed, other])
    db.commit()
    seed.seed_defaults(db, settings)
    assert feed.search_url_template == "https://feed.animetosho.net/rss2?q={query}"
    assert other.search_url_template is None  # exact URL match only
    feed.search_url_template = None  # user cleared it deliberately
    db.commit()
    seed.seed_defaults(db, settings)
    assert feed.search_url_template is None
    events = [a.event_type for a in db.scalars(select(ActivityLog))]
    assert events.count("feed_search_template_backfilled") == 1


def test_schema_validators() -> None:
    with pytest.raises(ValidationError, match="invalid regex"):
        RuleIn(series_id=1, name="r", regex="(unclosed")
    assert RuleIn(series_id=1, name="r", regex="").regex is None
    assert SeriesIn(name="  Re:Zero  ").name == "ReZero"
    with pytest.raises(ValidationError):
        SeriesIn(name="..")
    with pytest.raises(ValidationError):
        SeriesIn(name="X", season_folder_format="{season.__class__}")
    with pytest.raises(ValidationError):
        SeriesIn(name="X", path_override="../x")
    with pytest.raises(ValidationError):
        QbitConfigIn(url="ftp://x")
