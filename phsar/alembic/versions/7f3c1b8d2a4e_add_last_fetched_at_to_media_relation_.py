"""Add last_fetched_at to media_relation_edges so the backfiller can
distinguish "fetched and got zero relations" from "never fetched".

Pre-fix the gate read `if sidecar.edges:` — falsy for the legitimate
empty-relations case (standalone movies/specials), so those rows
re-fetched from MAL on every restart forever. After the column lands,
the gate reads `if sidecar.last_fetched_at is not None:` and zero-
relation rows stop costing 1 req/s per restart.

Revision ID: 7f3c1b8d2a4e
Revises: c5e8a2f9b1d3
Create Date: 2026-05-17 08:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7f3c1b8d2a4e"
down_revision: Union[str, None] = "c5e8a2f9b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "media_relation_edges",
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill: every existing sidecar row was written by the v0.14.1
    # backfiller or by save_service / update_sweep, all of which fetched
    # from MAL before writing. `modified_at` is the most recent of those
    # write timestamps, so it's a safe lower bound for "last MAL sync".
    # The empty-relations rows specifically (the rows this migration
    # exists to fix) get stamped here so they stop re-fetching.
    op.execute(
        "UPDATE media_relation_edges "
        "SET last_fetched_at = modified_at "
        "WHERE last_fetched_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("media_relation_edges", "last_fetched_at")
