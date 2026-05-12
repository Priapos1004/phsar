"""Add backup to JobKind enum

Revision ID: fc2c22360cd0
Revises: 8d4f2a1c9e7b
Create Date: 2026-05-11 17:30:00.000000

Adds the `backup` enum value so the jobs table can carry backup-creation
work alongside user_scrape / update_sweep / seasonal_sweep. The backend
flips the admin backup endpoints from synchronous pg_dump to enqueue-and-
return-202 in the same release.

PostgreSQL 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as
long as the new value isn't referenced in the same transaction, so this
migration runs cleanly under Alembic's default transaction wrap.

"""
from typing import Sequence, Union

from alembic import op


revision: str = "fc2c22360cd0"
down_revision: Union[str, None] = "8d4f2a1c9e7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS makes a retry after a partially-applied migration safe.
    op.execute("ALTER TYPE jobkind ADD VALUE IF NOT EXISTS 'backup'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — recreate the enum and
    # re-cast the column. Any leftover backup-kind rows would block the
    # cast, so delete them first; a downgrade implies async-backup support
    # is being rolled back and those rows can't be processed anyway.
    op.execute("DELETE FROM jobs WHERE kind = 'backup'")
    op.execute("ALTER TYPE jobkind RENAME TO jobkind_old")
    op.execute(
        "CREATE TYPE jobkind AS ENUM "
        "('user_scrape', 'update_sweep', 'seasonal_sweep')"
    )
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN kind TYPE jobkind "
        "USING kind::text::jobkind"
    )
    op.execute("DROP TYPE jobkind_old")
