"""Add per-user user_scrape recency index for daily cap

Revision ID: b8e5d3a1c2f9
Revises: a3f7c2e9b1d8
Create Date: 2026-05-25 13:00:00.000000

Backs `JobDAO.count_user_scrapes_in_window`, fired on every
/jobs/scrape POST to enforce the rolling 24h cap. Without this
index the daily check rides `ix_jobs_user_status` (user, status),
which seeks all of a user's jobs and rechecks kind + created_at
on the heap — O(total user_scrape rows for that user). At 50
jobs/day that crosses 18k rows in year one for a power user, so
move the work to an O(in-window-rows) partial composite.

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b8e5d3a1c2f9"
down_revision: Union[str, None] = "a3f7c2e9b1d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_jobs_user_scrape_recent
        ON jobs (requested_by_user_id, created_at DESC)
        WHERE kind = 'user_scrape'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_user_scrape_recent")
