"""v0.15.0 watchlist rework — one tag per entry + immutable default tag

Revision ID: b7f3a1c9d2e5
Revises: f1b9c4e2a7d3
Create Date: 2026-07-20 12:00:00.000000

Reworks the watchlist from a many-to-many tag model to one tag per entry:

- Drops the `watchlist_tag` join table.
- Adds a required `watchlist.tag_id` FK (ON DELETE CASCADE) — one tag per entry.
- Makes `watchlist.priority` NOT NULL (server_default 3) — the UI defaults to 3.
- Adds `tag.is_default` (the immutable per-user "Watchlist" tag) + a partial
  unique index guaranteeing at most one default tag per user.
- Adds `ix_watchlist_user_modified` for the paginated overview listing.

The `watchlist` / `tag` / `watchlist_tag` tables are empty in every environment
(the feature never shipped a write path), so the NOT NULL `tag_id` add and the
priority NOT NULL flip are safe without a data backfill.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7f3a1c9d2e5"
down_revision: Union[str, None] = "f1b9c4e2a7d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the many-to-many join table (replaced by watchlist.tag_id).
    op.drop_index(op.f("ix_watchlist_tag_id"), table_name="watchlist_tag")
    op.drop_table("watchlist_tag")

    # tag.is_default — the immutable per-user default tag.
    op.add_column(
        "tag",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "uq_tag_one_default_per_user",
        "tag",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    # Keep the DB in sync with the model's new server_default for color.
    op.alter_column("tag", "color", existing_type=sa.String(length=7), server_default="#808080")

    # watchlist.tag_id — one tag per entry (empty table, so add NOT NULL directly).
    op.add_column("watchlist", sa.Column("tag_id", sa.Integer(), nullable=False))
    op.create_foreign_key(
        "watchlist_tag_id_fkey", "watchlist", "tag", ["tag_id"], ["id"], ondelete="CASCADE"
    )

    # priority becomes non-optional (server_default 3).
    op.alter_column(
        "watchlist",
        "priority",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="3",
    )

    # Paginated overview listing: WHERE user_id = ? ORDER BY modified_at DESC.
    op.create_index(
        "ix_watchlist_user_modified",
        "watchlist",
        ["user_id", sa.literal_column("modified_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_user_modified", table_name="watchlist")
    op.alter_column(
        "watchlist",
        "priority",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )
    op.drop_constraint("watchlist_tag_id_fkey", "watchlist", type_="foreignkey")
    op.drop_column("watchlist", "tag_id")

    op.alter_column("tag", "color", existing_type=sa.String(length=7), server_default=None)
    op.drop_index("uq_tag_one_default_per_user", table_name="tag")
    op.drop_column("tag", "is_default")

    # Recreate the join table (mirrors the initial schema).
    op.create_table(
        "watchlist_tag",
        sa.Column("watchlist_id", sa.Integer(), nullable=True),
        sa.Column("tag_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlist.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uuid"),
        sa.UniqueConstraint("watchlist_id", "tag_id", name="unique_watchlist_tag"),
    )
    op.create_index(op.f("ix_watchlist_tag_id"), "watchlist_tag", ["id"], unique=False)
