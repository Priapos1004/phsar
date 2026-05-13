"""Add expression index for jobs dedup lookup

Revision ID: 9a7e3b8c1d4f
Revises: fc2c22360cd0
Create Date: 2026-05-13 09:00:00.000000

Speeds up `JobDAO.find_recent_scrape_for_query` — the dedup check that fires
on every `/jobs/scrape` POST. Without this index, the query degenerates to a
seq-scan with per-row function evaluation as the jobs history grows; current
row counts are fine but the seasonal sweep enqueues hundreds of system
user_scrape rows per week, so the table grows monotonically.

The composite key matches the query exactly: kind filter is encoded in the
partial-index predicate, normalized query is the first column, created_at
DESC supports the ORDER BY ... LIMIT 1 tail.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9a7e3b8c1d4f'
down_revision: Union[str, None] = 'fc2c22360cd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_jobs_scrape_query
        ON jobs (lower(trim(payload ->> 'query')), created_at DESC)
        WHERE kind = 'user_scrape'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_scrape_query")
