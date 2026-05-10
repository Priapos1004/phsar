"""Add indexes for update_sweep tier-selection query

Revision ID: 8d4f2a1c9e7b
Revises: 2f1a8e3c4d5b
Create Date: 2026-05-10 22:30:00.000000

AnimeDAO.select_due_for_sweep performs two correlated EXISTS subqueries
on `media` plus an ORDER BY on `anime_freshness.last_checked_at`. Without
supporting indexes the planner falls back to seq scans, and the query
cost grows linearly with catalog size — by 50k anime the sweep's first
action is a multi-second query before any I/O work.

- ix_anime_freshness_last_checked_at: ORDER BY column, NULLS FIRST so
  never-checked anime sort to the front.
- ix_media_airing_now: partial index on (anime_id) WHERE airing_status =
  'Currently Airing' — supports the airing_now EXISTS without indexing
  the bulk of finished-airing rows.
- ix_media_main_aired_from: composite (anime_id, relation_type,
  aired_from) — supports the recent_main EXISTS as an index-only scan.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "8d4f2a1c9e7b"
down_revision: Union[str, None] = "2f1a8e3c4d5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_anime_freshness_last_checked_at",
        "anime_freshness",
        ["last_checked_at"],
        unique=False,
        postgresql_using="btree",
    )
    op.create_index(
        "ix_media_airing_now",
        "media",
        ["anime_id"],
        unique=False,
        postgresql_where=sa.text("airing_status = 'Currently Airing'"),
    )
    op.create_index(
        "ix_media_main_aired_from",
        "media",
        ["anime_id", "relation_type", "aired_from"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_media_main_aired_from", table_name="media")
    op.drop_index("ix_media_airing_now", table_name="media")
    op.drop_index("ix_anime_freshness_last_checked_at", table_name="anime_freshness")
