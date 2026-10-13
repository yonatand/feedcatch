"""SQLAlchemy ORM models. Mirrors `.claude/rules/architecture.md` "Data model".

JSON columns are stored under `<name>_json` DB column names but exposed as `<name>` attributes
(e.g. `Series.aliases` -> column `aliases_json`) so pydantic `from_attributes` maps directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Dialect,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DEFAULT_SEASON_FOLDER_FORMAT = "Season {season:02d}"


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stores naive UTC in SQLite; always returns aware UTC datetimes.

    Naive inputs are assumed to already be UTC.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class FeedSource(Base):
    __tablename__ = "feed_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    backfill_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="skip")
    etag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), nullable=False, default="never")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    initial_poll_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    entries: Mapped[list[FeedEntry]] = relationship(
        back_populates="feed", cascade="all, delete-orphan", passive_deletes=True
    )


class FeedEntry(Base):
    __tablename__ = "feed_entries"
    __table_args__ = (
        UniqueConstraint("feed_id", "guid", name="uq_feed_entries_feed_guid"),
        Index("ix_feed_entries_first_seen_at", "first_seen_at"),
        Index("ix_feed_entries_infohash", "infohash"),
        Index("ix_feed_entries_outcome", "outcome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feed_sources.id", ondelete="CASCADE"), nullable=False)
    guid: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    magnet_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    torrent_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    nzb_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    infohash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_historical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="unprocessed")
    outcome_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed: Mapped[dict[str, Any] | None] = mapped_column("parsed_json", JSON, nullable=True)

    feed: Mapped[FeedSource] = relationship(back_populates="entries")
    evaluations: Mapped[list[Evaluation]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", passive_deletes=True
    )
    downloads: Mapped[list[Download]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", passive_deletes=True
    )


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    # NOCASE collation makes the UNIQUE constraint case-insensitive (ASCII) in SQLite.
    name: Mapped[str] = mapped_column(String(255, collation="NOCASE"), nullable=False, unique=True)
    aliases: Mapped[list[str]] = mapped_column("aliases_json", JSON, nullable=False, default=list)
    monitored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    season_folder_format: Mapped[str] = mapped_column(String(255), nullable=False, default=DEFAULT_SEASON_FOLDER_FORMAT)
    path_override: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    category_override: Mapped[str | None] = mapped_column(String(255), nullable=True)

    seasons: Mapped[list[Season]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Season.season_number",
    )
    rules: Mapped[list[Rule]] = relationship(
        back_populates="series", cascade="all, delete-orphan", passive_deletes=True
    )
    downloads: Mapped[list[Download]] = relationship(
        back_populates="series", cascade="all, delete-orphan", passive_deletes=True
    )


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("series_id", "season_number", name="uq_seasons_series_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), nullable=False)
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    monitored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    path_override: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    episode_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    absolute_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    absolute_max: Mapped[int | None] = mapped_column(Integer, nullable=True)

    series: Mapped[Series] = relationship(back_populates="seasons")
    rules: Mapped[list[Rule]] = relationship(
        back_populates="season", cascade="all, delete-orphan", passive_deletes=True
    )
    downloads: Mapped[list[Download]] = relationship(
        back_populates="season", cascade="all, delete-orphan", passive_deletes=True
    )


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), nullable=False)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    release_group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    require_group_prefix: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    include_keywords: Mapped[list[str]] = mapped_column("include_keywords_json", JSON, nullable=False, default=list)
    exclude_keywords: Mapped[list[str]] = mapped_column("exclude_keywords_json", JSON, nullable=False, default=list)
    resolutions: Mapped[list[str]] = mapped_column("resolutions_json", JSON, nullable=False, default=list)
    sources: Mapped[list[str]] = mapped_column("sources_json", JSON, nullable=False, default=list)
    codecs: Mapped[list[str]] = mapped_column("codecs_json", JSON, nullable=False, default=list)
    language_keywords: Mapped[list[str]] = mapped_column("language_keywords_json", JSON, nullable=False, default=list)
    min_size_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_size_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    regex: Mapped[str | None] = mapped_column(Text, nullable=True)

    series: Mapped[Series] = relationship(back_populates="rules")
    season: Mapped[Season | None] = relationship(back_populates="rules")
    evaluations: Mapped[list[Evaluation]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", passive_deletes=True
    )


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (UniqueConstraint("entry_id", "rule_id", name="uq_evaluations_entry_rule"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    entry_id: Mapped[int] = mapped_column(ForeignKey("feed_entries.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"), nullable=False)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id", ondelete="SET NULL"), nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conditions: Mapped[list[dict[str, Any]]] = mapped_column("conditions_json", JSON, nullable=False, default=list)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    entry: Mapped[FeedEntry] = relationship(back_populates="evaluations")
    rule: Mapped[Rule] = relationship(back_populates="evaluations")
    season: Mapped[Season | None] = relationship()


class Download(Base):
    __tablename__ = "downloads"
    __table_args__ = (
        Index(
            "ux_downloads_episode_active",
            "season_id",
            "episode_number",
            unique=True,
            sqlite_where=text("status != 'failed' AND forced = 0"),
        ),
        Index(
            "ux_downloads_infohash_active",
            "infohash",
            unique=True,
            sqlite_where=text("infohash IS NOT NULL AND status != 'failed'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)
    entry_id: Mapped[int] = mapped_column(ForeignKey("feed_entries.id", ondelete="CASCADE"), nullable=False)
    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), nullable=False)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id", ondelete="SET NULL"), nullable=True)
    infohash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    save_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    qbit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    qbit_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    qbit_progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    qbit_save_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    forced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    entry: Mapped[FeedEntry] = relationship(back_populates="downloads")
    series: Mapped[Series] = relationship(back_populates="downloads")
    season: Mapped[Season] = relationship(back_populates="downloads")
    rule: Mapped[Rule | None] = relationship()


class ActivityLog(Base):
    __tablename__ = "activity_log"
    __table_args__ = (Index("ix_activity_log_ts", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column("details_json", JSON, nullable=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("feed_entries.id", ondelete="SET NULL"), nullable=True)
    download_id: Mapped[int | None] = mapped_column(ForeignKey("downloads.id", ondelete="SET NULL"), nullable=True)


class SettingKV(Base):
    """Key/value settings table (`settings`). Values are JSON."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column("value_json", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)
