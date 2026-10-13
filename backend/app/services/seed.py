"""Idempotent demo seed: AnimeTosho feed + Black Clover S2 / DKB 1080p rule (series NOT monitored)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import FeedSource, Rule, Season, Series
from app.services import settings_store
from app.services.paths import DEFAULT_SEASON_FOLDER_FORMAT

DEFAULT_FEED_URL = "https://feed.animetosho.net/rss2"


def seed_demo(db: Session, settings: Settings) -> bool:
    """Create defaults + demo data once (guarded by settings key `demo_seeded`). Commits. Returns True if seeded."""
    settings_store.ensure_defaults(db)
    if settings_store.get(db, settings_store.DEMO_SEEDED, False):
        db.commit()
        return False

    url = settings.FEED_URL or DEFAULT_FEED_URL
    if db.scalar(select(FeedSource).where(FeedSource.url == url)) is None:
        db.add(FeedSource(name="AnimeTosho", url=url, enabled=True, poll_interval_minutes=15, backfill_mode="skip"))

    series = db.scalar(select(Series).where(func.lower(Series.name) == "black clover"))
    if series is None:
        series = Series(
            name="Black Clover",
            aliases=["Black.Clover", "Black_Clover"],
            monitored=False,
            season_folder_format=DEFAULT_SEASON_FOLDER_FORMAT,
        )
        db.add(series)
        db.flush()

    season = db.scalar(select(Season).where(Season.series_id == series.id, Season.season_number == 2))
    if season is None:
        season = Season(series_id=series.id, season_number=2, monitored=True)
        db.add(season)
        db.flush()

    if db.scalar(select(Rule).where(Rule.series_id == series.id, Rule.name == "DKB 1080p")) is None:
        db.add(
            Rule(
                series_id=series.id,
                season_id=season.id,
                name="DKB 1080p",
                enabled=True,
                priority=10,
                release_group="DKB",
                require_group_prefix=True,
                resolutions=["1080p"],
            )
        )
    settings_store.set(db, settings_store.DEMO_SEEDED, True)
    db.commit()
    return True
