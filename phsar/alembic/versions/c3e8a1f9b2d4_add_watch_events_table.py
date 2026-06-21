"""Add watch_events table (rewatch tracking)

Revision ID: c3e8a1f9b2d4
Revises: b2d9f4a17c3e
Create Date: 2026-06-21 11:00:00.000000

v0.14.10 feature 2. Append-only watch/rewatch log keyed to (user_id, media_id);
`watched_count` is derived as COUNT(events), never stored. Backfills one event per
existing `completed` rating, stamped at the rating's created_at so the seeded
history enters the time series at its honest age (same gen_random_uuid() pattern as
the freshness-sidecar backfills). on_hold/dropped ratings get no seed event — they
were never completed. See [app/models/watch_event.py].

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e8a1f9b2d4"
down_revision: Union[str, None] = "b2d9f4a17c3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watch_events",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column(
            "watched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "modified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index(op.f("ix_watch_events_id"), "watch_events", ["id"], unique=False)
    op.create_index("ix_watch_events_user_media", "watch_events", ["user_id", "media_id"], unique=False)
    op.create_index("ix_watch_events_watched_at", "watch_events", ["watched_at"], unique=False)

    # Seed one event per existing completed rating at the rating's own created_at, so the
    # first-completion history is present for already-rated media without a re-rate.
    op.execute(
        "INSERT INTO watch_events (user_id, media_id, watched_at, uuid, created_at, modified_at) "
        "SELECT user_id, media_id, created_at, gen_random_uuid(), created_at, created_at "
        "FROM ratings WHERE watch_status = 'completed'"
    )


def downgrade() -> None:
    op.drop_index("ix_watch_events_watched_at", table_name="watch_events")
    op.drop_index("ix_watch_events_user_media", table_name="watch_events")
    op.drop_index(op.f("ix_watch_events_id"), table_name="watch_events")
    op.drop_table("watch_events")
