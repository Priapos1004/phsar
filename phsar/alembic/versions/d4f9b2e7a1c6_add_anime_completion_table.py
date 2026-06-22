"""Add anime_completion table (admin story-complete flag)

Revision ID: d4f9b2e7a1c6
Revises: c3e8a1f9b2d4
Create Date: 2026-06-21 12:00:00.000000

v0.14.10 feature 3. 1:1 sidecar to `anime`; row-presence = admin marked the
story complete. Starts empty (no backfill — there's no signal to infer it from;
admins curate it). FK to anime CASCADE; marked_by_user_id SET NULL so deleting
the admin account doesn't un-mark. See [app/models/anime_completion.py].

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f9b2e7a1c6"
down_revision: Union[str, None] = "c3e8a1f9b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "anime_completion",
        sa.Column("anime_id", sa.Integer(), nullable=False),
        sa.Column("marked_by_user_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["anime_id"], ["anime.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["marked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("anime_id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index(op.f("ix_anime_completion_id"), "anime_completion", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_anime_completion_id"), table_name="anime_completion")
    op.drop_table("anime_completion")
