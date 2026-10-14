"""Episodes, release search, generic metadata providers

Revision ID: 0003_episodes
Revises: 0002_anilist
Create Date: 2026-10-14

- seasons: metadata_provider, metadata_id, metadata_refreshed_at
- episodes: new table
- feed_sources: search_url_template
- series: anilist_id -> (metadata_provider='anilist', metadata_id=str(id)); anilist_json -> metadata_json
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0003_episodes"
down_revision: str | None = "0002_anilist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _convert_info(raw: Any, anilist_id: int) -> dict[str, Any] | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if not isinstance(raw, dict):
        return None
    english, romaji, native = raw.get("title_english"), raw.get("title_romaji"), raw.get("title_native")
    title = english or romaji or native
    alt = [t for t in (romaji, english) if t and t != title]
    return {
        "provider": "anilist",
        "id": str(anilist_id),
        "title": title,
        "original_title": native,
        "alt_titles": alt,
        "kind": "anime",
        "format": raw.get("format"),
        "status": raw.get("status"),
        "year": raw.get("season_year"),
        "episodes": raw.get("episodes"),
        "site_url": raw.get("site_url"),
    }


def upgrade() -> None:
    with op.batch_alter_table("feed_sources") as batch:
        batch.add_column(sa.Column("search_url_template", sa.String(2048), nullable=True))

    with op.batch_alter_table("seasons") as batch:
        batch.add_column(sa.Column("metadata_provider", sa.String(16), nullable=True))
        batch.add_column(sa.Column("metadata_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("metadata_refreshed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_seasons_metadata", "seasons", ["metadata_provider", "metadata_id"])

    with op.batch_alter_table("series") as batch:
        batch.add_column(sa.Column("metadata_provider", sa.String(16), nullable=True))
        batch.add_column(sa.Column("metadata_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("metadata_json", sa.JSON(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, anilist_id, anilist_json FROM series WHERE anilist_id IS NOT NULL")).all()
    for sid, aid, raw in rows:
        info = _convert_info(raw, int(aid))
        conn.execute(
            sa.text(
                "UPDATE series SET metadata_provider='anilist', metadata_id=:mid, metadata_json=:info WHERE id=:id"
            ),
            {"mid": str(aid), "info": json.dumps(info) if info is not None else None, "id": sid},
        )

    # Native DROP COLUMN (SQLite >= 3.35): a batch table rebuild would DROP `series`, and with foreign_keys=ON that
    # cascades to seasons/rules/downloads. It also keeps the NOCASE collation of `series.name`.
    op.drop_index("ux_series_anilist_id", table_name="series")
    op.execute("ALTER TABLE series DROP COLUMN anilist_json")
    op.execute("ALTER TABLE series DROP COLUMN anilist_id")
    op.create_index("ux_series_metadata", "series", ["metadata_provider", "metadata_id"], unique=True)

    op.create_table(
        "episodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("air_date", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.UniqueConstraint("season_id", "episode_number", name="uq_episodes_season_number"),
    )
    op.create_index("ix_episodes_air_date", "episodes", ["air_date"])


def downgrade() -> None:
    op.drop_index("ix_episodes_air_date", table_name="episodes")
    op.drop_table("episodes")
    op.drop_index("ux_series_metadata", table_name="series")
    with op.batch_alter_table("series") as batch:
        batch.add_column(sa.Column("anilist_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("anilist_json", sa.JSON(), nullable=True))
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE series SET anilist_id=CAST(metadata_id AS INTEGER) WHERE metadata_provider='anilist'"))
    for col in ("metadata_json", "metadata_id", "metadata_provider"):
        op.execute(f"ALTER TABLE series DROP COLUMN {col}")
    op.create_index("ux_series_anilist_id", "series", ["anilist_id"], unique=True)
    op.drop_index("ix_seasons_metadata", table_name="seasons")
    for col in ("metadata_refreshed_at", "metadata_id", "metadata_provider"):
        op.execute(f"ALTER TABLE seasons DROP COLUMN {col}")
    op.execute("ALTER TABLE feed_sources DROP COLUMN search_url_template")
