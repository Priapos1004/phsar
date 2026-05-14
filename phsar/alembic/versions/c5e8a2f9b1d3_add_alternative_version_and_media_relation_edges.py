"""Add AlternativeVersion to RelationType + media_relation_edges sidecar

Revision ID: c5e8a2f9b1d3
Revises: 4b8f1e3c7d0a
Create Date: 2026-05-14 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "c5e8a2f9b1d3"
down_revision: Union[str, None] = "4b8f1e3c7d0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS makes a retry after a partially-applied migration safe.
    op.execute("ALTER TYPE relationtype ADD VALUE IF NOT EXISTS 'AlternativeVersion'")

    # No backfill INSERT (unlike cb6055f6a525 for freshness): edges must
    # be re-fetched from MAL, not synthesized from local state. The
    # backfiller seeder fills these on first restart after upgrade.
    op.create_table(
        "media_relation_edges",
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column(
            "edges",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
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
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index(
        op.f("ix_media_relation_edges_id"),
        "media_relation_edges",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_media_relation_edges_id"), table_name="media_relation_edges"
    )
    op.drop_table("media_relation_edges")

    # Postgres has no ALTER TYPE ... DROP VALUE — recreate the enum and
    # re-cast the column. Demote AlternativeVersion rows to SideStory so
    # the cast doesn't fail.
    op.execute(
        "UPDATE media SET relation_type = 'SideStory' "
        "WHERE relation_type = 'AlternativeVersion'"
    )
    op.execute("ALTER TYPE relationtype RENAME TO relationtype_old")
    op.execute(
        "CREATE TYPE relationtype AS ENUM "
        "('Main', 'Summary', 'Crossover', 'SideStory')"
    )
    op.execute(
        "ALTER TABLE media ALTER COLUMN relation_type TYPE relationtype "
        "USING relation_type::text::relationtype"
    )
    op.execute("DROP TYPE relationtype_old")
