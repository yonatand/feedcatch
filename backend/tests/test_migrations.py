from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import run_migrations
from app.models import Base, Download, FeedEntry, FeedSource, Season, Series


def test_schema_matches_models(db_url: str) -> None:
    run_migrations(db_url)
    run_migrations(db_url)  # idempotent
    engine = create_engine(db_url)
    try:
        insp = inspect(engine)
        db_tables = set(insp.get_table_names()) - {"alembic_version"}
        assert db_tables == set(Base.metadata.tables)
        for name, table in Base.metadata.tables.items():
            db_cols = {c["name"] for c in insp.get_columns(name)}
            assert db_cols == {c.name for c in table.columns}, name
            db_idx = {i["name"] for i in insp.get_indexes(name)}
            model_idx = {i.name for i in table.indexes}
            assert model_idx <= db_idx, name
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='ux_downloads_episode_active'")).scalar()
            assert sql is not None and "WHERE" in sql
    finally:
        engine.dispose()


def _setup(db: Session) -> tuple[FeedEntry, Series, Season]:
    feed = FeedSource(name="f", url="https://example.org/rss")
    series = Series(name="Black Clover", aliases=[])
    db.add_all([feed, series])
    db.flush()
    season = Season(series_id=series.id, season_number=2)
    entry = FeedEntry(feed_id=feed.id, guid="g1", title="t")
    db.add_all([season, entry])
    db.flush()
    return entry, series, season


def _dl(entry: FeedEntry, series: Series, season: Season, **kw: object) -> Download:
    base: dict[str, object] = dict(
        entry_id=entry.id,
        series_id=series.id,
        season_id=season.id,
        episode_number=1,
        source_url="magnet:?xt=urn:btih:" + "a" * 40,
        source_url_kind="magnet",
        save_path="/home/qbittorrent-nox/media/Black Clover/Season 02",
    )
    base.update(kw)
    return Download(**base)


def test_episode_partial_unique(db: Session) -> None:
    entry, series, season = _setup(db)
    first = _dl(entry, series, season, status="submitted")
    db.add(first)
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(_dl(entry, series, season, status="pending"))
        db.flush()
    # forced rows are exempt
    with db.begin_nested():
        db.add(_dl(entry, series, season, status="pending", forced=True))
        db.flush()
    # once the active one fails, a new active one is allowed
    first.status = "failed"
    db.flush()
    with db.begin_nested():
        db.add(_dl(entry, series, season, status="pending"))
        db.flush()


def test_previous_forced_allows_new(db: Session) -> None:
    entry, series, season = _setup(db)
    db.add(_dl(entry, series, season, status="submitted", forced=True))
    db.flush()
    db.add(_dl(entry, series, season, status="pending"))
    db.flush()


def test_infohash_partial_unique(db: Session) -> None:
    entry, series, season = _setup(db)
    h = "b" * 40
    first = _dl(entry, series, season, infohash=h, status="submitted")
    db.add(first)
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(_dl(entry, series, season, episode_number=2, infohash=h))
        db.flush()
    first.status = "failed"
    db.flush()
    with db.begin_nested():
        db.add(_dl(entry, series, season, episode_number=2, infohash=h))
        db.flush()
    # NULL infohashes never collide
    db.add(_dl(entry, series, season, episode_number=3, infohash=None))
    db.add(_dl(entry, series, season, episode_number=4, infohash=None))
    db.flush()


def test_series_name_unique_case_insensitive(db: Session) -> None:
    db.add(Series(name="Black Clover", aliases=[]))
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(Series(name="black clover", aliases=[]))
        db.flush()


def test_cascade_delete_series(db: Session) -> None:
    entry, series, season = _setup(db)
    db.add(_dl(entry, series, season))
    db.commit()
    db.delete(series)
    db.commit()
    assert db.query(Season).count() == 0
    assert db.query(Download).count() == 0


def test_utc_datetime_roundtrip(db: Session) -> None:
    feed = FeedSource(name="f", url="https://example.org/a")
    plus2 = timezone(timedelta(hours=2))
    feed.last_checked_at = datetime(2026, 1, 1, 12, 0, tzinfo=plus2)
    db.add(feed)
    db.commit()
    db.expire_all()
    got = db.get(FeedSource, feed.id)
    assert got is not None and got.last_checked_at is not None
    assert got.last_checked_at.tzinfo is not None
    assert got.last_checked_at == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert got.created_at.tzinfo is not None
