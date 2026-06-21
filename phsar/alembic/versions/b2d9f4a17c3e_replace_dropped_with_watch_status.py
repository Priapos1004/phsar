"""Replace ratings.dropped boolean with watch_status enum

Revision ID: b2d9f4a17c3e
Revises: a1c4e8f02b6d
Create Date: 2026-06-21 10:00:00.000000

v0.14.10 feature 1. The legacy `dropped` boolean could only express
Completed vs Dropped; `watch_status` adds an `on_hold` state (a paused
but not abandoned anime) so a future "continue watching" surface can
distinguish the two. Backfill maps dropped=true -> 'dropped', else
'completed'; `on_hold` is unreachable from legacy data (only new writes
set it). See [app/models/ratings.py] for the enum rationale.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2d9f4a17c3e"
down_revision: Union[str, None] = "a1c4e8f02b6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the enum TYPE explicitly (create_type=False on the column below
    # so add_column doesn't try to create it a second time).
    watchstatus = postgresql.ENUM(
        "completed", "on_hold", "dropped", name="watchstatus", create_type=False
    )
    watchstatus.create(op.get_bind(), checkfirst=True)

    # Add NOT NULL with server_default so every existing row gets 'completed'
    # immediately, then promote the dropped rows.
    op.add_column(
        "ratings",
        sa.Column(
            "watch_status",
            watchstatus,
            nullable=False,
            server_default="completed",
        ),
    )
    op.execute("UPDATE ratings SET watch_status = 'dropped' WHERE dropped = true")
    op.drop_column("ratings", "dropped")


def downgrade() -> None:
    op.add_column(
        "ratings",
        sa.Column("dropped", sa.Boolean(), nullable=True, server_default=sa.false()),
    )
    # Lossy: on_hold collapses back to dropped=false (looks completed).
    op.execute("UPDATE ratings SET dropped = (watch_status = 'dropped')")
    op.drop_column("ratings", "watch_status")
    # SQLAlchemy creates ENUMs as standalone Postgres TYPEs; drop on downgrade
    # so a re-upgrade doesn't collide.
    sa.Enum(name="watchstatus").drop(op.get_bind(), checkfirst=True)
