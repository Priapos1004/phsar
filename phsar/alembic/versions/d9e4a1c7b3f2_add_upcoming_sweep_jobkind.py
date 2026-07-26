"""Add upcoming_sweep to JobKind enum

Revision ID: d9e4a1c7b3f2
Revises: b7f3a1c9d2e5
Create Date: 2026-07-26 12:00:00.000000

Adds the `upcoming_sweep` enum value so the jobs table can carry the
next-season discovery sweep alongside seasonal_sweep. It reuses the
seasonal_sweep dispatcher (targeting the next season off job.kind) and is
scheduled on Wednesdays in the last month of the quarter.

PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as long
as the new value isn't referenced in the same transaction, so this runs
cleanly under Alembic's default transaction wrap. `AFTER 'seasonal_sweep'`
keeps the PG enum order aligned with the Python JobKind declaration order.

"""
from typing import Sequence, Union

from alembic import op

revision: str = "d9e4a1c7b3f2"
down_revision: Union[str, None] = "b7f3a1c9d2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS makes a retry after a partially-applied migration safe.
    op.execute(
        "ALTER TYPE jobkind ADD VALUE IF NOT EXISTS 'upcoming_sweep' AFTER 'seasonal_sweep'"
    )


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — recreate the enum and re-cast
    # the column. Any leftover upcoming_sweep rows would block the cast, so
    # delete them first (a downgrade rolls back next-season sweep support and
    # those rows can't be processed anyway).
    op.execute("DELETE FROM jobs WHERE kind = 'upcoming_sweep'")
    op.execute("ALTER TYPE jobkind RENAME TO jobkind_old")
    op.execute(
        "CREATE TYPE jobkind AS ENUM "
        "('user_scrape', 'update_sweep', 'seasonal_sweep', 'backup', 'restore')"
    )
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN kind TYPE jobkind "
        "USING kind::text::jobkind"
    )
    op.execute("DROP TYPE jobkind_old")
