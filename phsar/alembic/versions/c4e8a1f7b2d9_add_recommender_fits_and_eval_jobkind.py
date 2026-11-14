"""Add the recommender's applied weights and the job that fits them

Revision ID: c4e8a1f7b2d9
Revises: 8d3f6a2c1e74
Create Date: 2026-11-14 18:00:00.000000

Creates `recommender_fits` empty, and adds the `recommender_eval` job kind that fills it. Until
its first applied fit the ranking keeps the committed weights, so nothing changes at deploy.

A leftover table is dropped first (`.claude/rules/database.md`); losing it costs only the
applied refits, and the ranking falls back to the committed weights.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c4e8a1f7b2d9'
down_revision: Union[str, None] = '8d3f6a2c1e74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # IF NOT EXISTS makes a retry after a partially-applied migration safe; the value is
    # not used in this transaction, which is what lets ADD VALUE run inside it.
    op.execute("ALTER TYPE jobkind ADD VALUE IF NOT EXISTS 'recommender_eval' AFTER 'galaxy_rebuild'")
    op.execute("DROP TABLE IF EXISTS recommender_fits")
    op.create_table('recommender_fits',
    sa.Column('weights', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('built_for', sa.String(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('modified_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('uuid')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('recommender_fits')
    # Postgres has no ALTER TYPE ... DROP VALUE: recreate the enum and re-cast the column.
    # A leftover recommender_eval row would block the cast, and its kind is gone anyway.
    # The partial indexes' predicates compare `kind` to a literal of the old type, which
    # blocks the re-cast: drop them around the cast and rebuild them as they were.
    op.execute("DELETE FROM jobs WHERE kind = 'recommender_eval'")
    op.execute("DROP INDEX IF EXISTS ix_jobs_user_scrape_recent")
    op.execute("DROP INDEX IF EXISTS ix_jobs_scrape_query")
    op.execute("ALTER TYPE jobkind RENAME TO jobkind_old")
    op.execute(
        "CREATE TYPE jobkind AS ENUM "
        "('user_scrape', 'update_sweep', 'seasonal_sweep', 'upcoming_sweep', 'backup', 'restore', 'galaxy_rebuild')"
    )
    op.execute("ALTER TABLE jobs ALTER COLUMN kind TYPE jobkind USING kind::text::jobkind")
    op.execute("DROP TYPE jobkind_old")
    op.execute(
        "CREATE INDEX ix_jobs_user_scrape_recent ON jobs (requested_by_user_id, created_at DESC) "
        "WHERE kind = 'user_scrape'"
    )
    op.execute(
        "CREATE INDEX ix_jobs_scrape_query ON jobs (lower(trim(payload ->> 'query')), created_at DESC) "
        "WHERE kind = 'user_scrape'"
    )
