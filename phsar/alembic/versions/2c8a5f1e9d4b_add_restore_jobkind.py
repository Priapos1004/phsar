"""Add restore to JobKind enum

Revision ID: 2c8a5f1e9d4b
Revises: 7f3c1b8d2a4e
Create Date: 2026-05-17 15:00:00.000000

See `app/models/job.py` JobKind.restore for the rationale (audit-only
rows, inserted synchronously by restore_backup; no worker dispatcher).

"""
from typing import Sequence, Union

from alembic import op


revision: str = "2c8a5f1e9d4b"
down_revision: Union[str, None] = "7f3c1b8d2a4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobkind ADD VALUE IF NOT EXISTS 'restore'")


def downgrade() -> None:
    # Postgres can't DROP an enum value; recreate the enum and recast.
    # Audit rows of kind=restore must go first or the cast trips.
    op.execute("DELETE FROM jobs WHERE kind = 'restore'")
    op.execute("ALTER TYPE jobkind RENAME TO jobkind_old")
    op.execute(
        "CREATE TYPE jobkind AS ENUM "
        "('user_scrape', 'update_sweep', 'seasonal_sweep', 'backup')"
    )
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN kind TYPE jobkind "
        "USING kind::text::jobkind"
    )
    op.execute("DROP TYPE jobkind_old")
