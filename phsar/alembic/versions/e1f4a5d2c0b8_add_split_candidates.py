"""Add split_candidates table

Revision ID: e1f4a5d2c0b8
Revises: 2c8a5f1e9d4b
Create Date: 2026-05-18 13:30:00.000000

Admin queue surfacing disjoint-franchise contamination detected by
`find_disjoint_franchises` in [app/services/relation_classifier.py].
See [app/models/split_candidate.py] for column-level rationale.

Schema mirrors merge_candidates conventions: BaseModel id/uuid/
created_at/modified_at, partial index on `(created_at) WHERE status =
'pending'` for admin list scans, FK CASCADE from anime so deleting
the source anime cleans up its row.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e1f4a5d2c0b8"
down_revision: Union[str, None] = "2c8a5f1e9d4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "split_candidates",
        sa.Column("anime_id", sa.Integer(), nullable=False),
        sa.Column("clusters", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "dismissed", "split", name="splitcandidatestatus"),
            nullable=False,
        ),
        sa.Column("detected_by", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index(
        op.f("ix_split_candidates_id"),
        "split_candidates",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_split_candidates_anime_id"),
        "split_candidates",
        ["anime_id"],
        unique=False,
    )
    op.create_index(
        "ix_split_candidates_pending",
        "split_candidates",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_split_candidates_pending",
        table_name="split_candidates",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(op.f("ix_split_candidates_anime_id"), table_name="split_candidates")
    op.drop_index(op.f("ix_split_candidates_id"), table_name="split_candidates")
    op.drop_table("split_candidates")
    # SQLAlchemy creates ENUMs as standalone Postgres TYPEs; autogenerate
    # leaves them behind on downgrade, which then collides on re-upgrade.
    sa.Enum(name="splitcandidatestatus").drop(op.get_bind(), checkfirst=True)
