"""Add delete_candidates table

Revision ID: c3a7e15b9d82
Revises: b6d1f0a4e93c
Create Date: 2026-09-13 11:00:00.000000

Admin queue for catalogue entries that should probably be removed. See
[app/models/delete_candidate.py] for column-level rationale — in particular why
`media_id` is SET NULL rather than CASCADE, and why the pending index is
partial-unique.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c3a7e15b9d82"
down_revision: Union[str, None] = "b6d1f0a4e93c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "delete_candidates",
        sa.Column("media_id", sa.Integer(), nullable=True),
        sa.Column("mal_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("name_eng", sa.String(), nullable=True),
        sa.Column("name_jap", sa.String(), nullable=True),
        sa.Column("detected_by", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "dismissed", "deleted", name="deletecandidatestatus"),
            nullable=False,
        ),
        sa.Column(
            "blacklisted",
            sa.Boolean(),
            server_default=sa.text("false"),
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
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index(
        op.f("ix_delete_candidates_media_id"),
        "delete_candidates",
        ["media_id"],
        unique=False,
    )
    op.create_index(
        "uq_delete_candidates_pending_mal_id",
        "delete_candidates",
        ["mal_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_delete_candidates_pending",
        "delete_candidates",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_delete_candidates_pending",
        table_name="delete_candidates",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(
        "uq_delete_candidates_pending_mal_id",
        table_name="delete_candidates",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(op.f("ix_delete_candidates_media_id"), table_name="delete_candidates")
    op.drop_table("delete_candidates")
    # SQLAlchemy creates ENUMs as standalone Postgres TYPEs; autogenerate
    # leaves them behind on downgrade, which then collides on re-upgrade.
    sa.Enum(name="deletecandidatestatus").drop(op.get_bind(), checkfirst=True)
