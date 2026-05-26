"""Add (created_at DESC) index on jobs for the admin Jobs Log

Revision ID: c4e8b2a7d6f1
Revises: b8e5d3a1c2f9
Create Date: 2026-05-26 09:00:00.000000

Backs `JobDAO.list_admin_paginated` — the admin Jobs Log tab's
default (unfiltered) view does `ORDER BY created_at DESC LIMIT 50`
plus a matching COUNT, and none of the existing job indexes cover
those without a filter (`ix_jobs_queued_by_age` is partial on
status='queued', the user_scrape indexes are partial on kind).

A non-partial composite isn't needed — admin reads of the full
jobs history are low-frequency, and a plain `(created_at DESC)`
btree is enough to flip both the COUNT and the ordered LIMIT to
index scans as the table grows past a few thousand rows.

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c4e8b2a7d6f1"
down_revision: Union[str, None] = "b8e5d3a1c2f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_created_at_desc "
        "ON jobs (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_created_at_desc")
