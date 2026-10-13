"""AniList metadata on series

Revision ID: 0002_anilist
Revises: 0001_initial
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_anilist"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("series") as batch:
        batch.add_column(sa.Column("anilist_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cover_url", sa.String(2048), nullable=True))
        batch.add_column(sa.Column("anilist_json", sa.JSON(), nullable=True))
    op.create_index("ux_series_anilist_id", "series", ["anilist_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_series_anilist_id", table_name="series")
    with op.batch_alter_table("series") as batch:
        batch.drop_column("anilist_json")
        batch.drop_column("cover_url")
        batch.drop_column("anilist_id")
