"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models import UTCDateTime

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:
    return sa.Column("created_at", UTCDateTime(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "feed_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("poll_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("backfill_mode", sa.String(16), nullable=False),
        sa.Column("etag", sa.String(512), nullable=True),
        sa.Column("last_modified", sa.String(128), nullable=True),
        sa.Column("last_checked_at", UTCDateTime(), nullable=True),
        sa.Column("last_success_at", UTCDateTime(), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("initial_poll_done", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("url"),
    )

    op.create_table(
        "feed_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("feed_id", sa.Integer(), sa.ForeignKey("feed_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guid", sa.String(1024), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("published_at", UTCDateTime(), nullable=True),
        sa.Column("first_seen_at", UTCDateTime(), nullable=False),
        sa.Column("magnet_url", sa.Text(), nullable=True),
        sa.Column("torrent_url", sa.Text(), nullable=True),
        sa.Column("nzb_url", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("infohash", sa.String(40), nullable=True),
        sa.Column("is_historical", sa.Boolean(), nullable=False),
        sa.Column("processed_at", UTCDateTime(), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("outcome_summary", sa.Text(), nullable=True),
        sa.Column("parsed_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("feed_id", "guid", name="uq_feed_entries_feed_guid"),
    )
    op.create_index("ix_feed_entries_first_seen_at", "feed_entries", ["first_seen_at"])
    op.create_index("ix_feed_entries_infohash", "feed_entries", ["infohash"])
    op.create_index("ix_feed_entries_outcome", "feed_entries", ["outcome"])

    op.create_table(
        "series",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("name", sa.String(255, collation="NOCASE"), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("season_folder_format", sa.String(255), nullable=False),
        sa.Column("path_override", sa.String(1024), nullable=True),
        sa.Column("category_override", sa.String(255), nullable=True),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "seasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season_number", sa.Integer(), nullable=False),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("path_override", sa.String(1024), nullable=True),
        sa.Column("episode_min", sa.Integer(), nullable=True),
        sa.Column("episode_max", sa.Integer(), nullable=True),
        sa.Column("absolute_min", sa.Integer(), nullable=True),
        sa.Column("absolute_max", sa.Integer(), nullable=True),
        sa.UniqueConstraint("series_id", "season_number", name="uq_seasons_series_number"),
    )

    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("release_group", sa.String(255), nullable=True),
        sa.Column("require_group_prefix", sa.Boolean(), nullable=False),
        sa.Column("include_keywords_json", sa.JSON(), nullable=False),
        sa.Column("exclude_keywords_json", sa.JSON(), nullable=False),
        sa.Column("resolutions_json", sa.JSON(), nullable=False),
        sa.Column("sources_json", sa.JSON(), nullable=False),
        sa.Column("codecs_json", sa.JSON(), nullable=False),
        sa.Column("language_keywords_json", sa.JSON(), nullable=False),
        sa.Column("min_size_mb", sa.Float(), nullable=True),
        sa.Column("max_size_mb", sa.Float(), nullable=True),
        sa.Column("regex", sa.Text(), nullable=True),
    )

    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("feed_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("matched", sa.Boolean(), nullable=False),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id", ondelete="SET NULL"), nullable=True),
        sa.Column("episode_number", sa.Integer(), nullable=True),
        sa.Column("conditions_json", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("entry_id", "rule_id", name="uq_evaluations_entry_rule"),
    )

    op.create_table(
        "downloads",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("feed_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("series.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("infohash", sa.String(40), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_url_kind", sa.String(16), nullable=False),
        sa.Column("save_path", sa.String(2048), nullable=False),
        sa.Column("category", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", UTCDateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("qbit_hash", sa.String(64), nullable=True),
        sa.Column("qbit_state", sa.String(64), nullable=True),
        sa.Column("qbit_progress", sa.Float(), nullable=True),
        sa.Column("qbit_save_path", sa.String(2048), nullable=True),
        sa.Column("forced", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ux_downloads_episode_active",
        "downloads",
        ["season_id", "episode_number"],
        unique=True,
        sqlite_where=sa.text("status != 'failed' AND forced = 0"),
    )
    op.create_index(
        "ux_downloads_infohash_active",
        "downloads",
        ["infohash"],
        unique=True,
        sqlite_where=sa.text("infohash IS NOT NULL AND status != 'failed'"),
    )

    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        _created_at(),
        sa.Column("ts", UTCDateTime(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("feed_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("download_id", sa.Integer(), sa.ForeignKey("downloads.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_activity_log_ts", "activity_log", ["ts"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        _created_at(),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("ix_activity_log_ts", table_name="activity_log")
    op.drop_table("activity_log")
    op.drop_index("ux_downloads_infohash_active", table_name="downloads")
    op.drop_index("ux_downloads_episode_active", table_name="downloads")
    op.drop_table("downloads")
    op.drop_table("evaluations")
    op.drop_table("rules")
    op.drop_table("seasons")
    op.drop_table("series")
    op.drop_index("ix_feed_entries_outcome", table_name="feed_entries")
    op.drop_index("ix_feed_entries_infohash", table_name="feed_entries")
    op.drop_index("ix_feed_entries_first_seen_at", table_name="feed_entries")
    op.drop_table("feed_entries")
    op.drop_table("feed_sources")
