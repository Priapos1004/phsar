"""Add media_freshness.stable_check_count + last_checked_at index

Revision ID: a1c4e8f02b6d
Revises: f3a9d2c5b8e4
Create Date: 2026-06-17 12:00:00.000000

v0.14.8 moves update_sweep *selection* to media granularity
(AnimeDAO.select_due_media_for_sweep). The media-level tier query needs:

- media_freshness.stable_check_count: per-media stability counter, the
  media-level analogue of anime_freshness.stable_check_count. server_default
  0 so existing rows default in place — NO explicit backfill UPDATE: each
  media simply burns its own 5-check stabilization window on the next sweeps.
- ix_media_freshness_last_checked_at: the new ORDER BY column (NULLS FIRST)
  and the column behind the due_weekly / due_long_tail staleness predicates;
  direct analogue of ix_anime_freshness_last_checked_at.

One-time herd note: every existing media's last_checked_at == its old
created_at (backfilled by the 7a migration), so the FIRST media-level sweep
after deploy finds the whole long-tail catalog due at once. It drains over
~catalog_size / JOBS_SWEEP_MAX_PER_RUN nights — the same one-time dynamic the
anime-level sweep had at its own launch, bounded by the 200-per-run cap.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1c4e8f02b6d"
down_revision: Union[str, None] = "f3a9d2c5b8e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "media_freshness",
        sa.Column(
            "stable_check_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_media_freshness_last_checked_at",
        "media_freshness",
        ["last_checked_at"],
        unique=False,
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_freshness_last_checked_at", table_name="media_freshness"
    )
    op.drop_column("media_freshness", "stable_check_count")
