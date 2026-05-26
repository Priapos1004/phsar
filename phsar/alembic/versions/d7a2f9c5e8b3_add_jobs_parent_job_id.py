"""Add parent_job_id FK on jobs for seasonal-sweep clustering

Revision ID: d7a2f9c5e8b3
Revises: c4e8b2a7d6f1
Create Date: 2026-05-26 10:00:00.000000

`seasonal_sweep` enqueues one system `user_scrape` per newly-
discovered MAL entry it finds — historically these landed as
flat rows in the Jobs Log with no visible link back to the
parent sweep. Add a self-referential FK so the dispatcher can
stamp the parent_job_id on each child, and the admin Jobs Log
can collapse the flock under the seasonal_sweep parent.

ON DELETE SET NULL: deleting the parent shouldn't cascade-
delete the child scrape rows — they're audit history. Partial
index because >99% of jobs (user-initiated scrapes, sweeps,
backups) are root rows with parent_job_id NULL; the small
partial index only covers the rows where lookups actually fire.

Existing rows stay NULL inside this migration — the FK is the
only DDL change here, and an Alembic data migration is harder
to reverse than DDL. Historical clustering is an opt-in
dev/ops step via `scripts/backfill_seasonal_sweep_parents.py`,
which attributes each NULL-user `user_scrape` to the closest
prior `seasonal_sweep`. Safe because `seasonal_sweep_dispatcher`
is the only production source of NULL-user user_scrapes.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d7a2f9c5e8b3"
down_revision: Union[str, None] = "c4e8b2a7d6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "parent_job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_parent_job_id "
        "ON jobs (parent_job_id) WHERE parent_job_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_parent_job_id")
    op.drop_column("jobs", "parent_job_id")
