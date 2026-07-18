"""Drop Crossover from the relationtype enum (v0.14.14)

Revision ID: f1b9c4e2a7d3
Revises: a7c3e9f1b2d4
Create Date: 2026-07-18 12:00:00.000000

MAL API v2 never emits a `crossover` relation — it routes cross-franchise
collab links (the Isekai Quartet shape) through `character`, which is already
excluded from edge capture. So the migration to the official API removed the
scraper's crossover BFS handling and the classifier's crossover branch, and
`RelationType.Crossover` can no longer be produced. The value is dead: 0 media
carry it and 0 sidecars carry a crossover edge (verified on the catalog).

PostgreSQL can't DROP an enum value, so recreate the type without it. The
`USING` cast can't fail because no row holds 'Crossover'. `media.relation_type`
is the only column on this type and has no server default, so the recreate is
a straight rebuild.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f1b9c4e2a7d3"
down_revision: Union[str, None] = "a7c3e9f1b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE relationtype RENAME TO relationtype_old")
    op.execute(
        "CREATE TYPE relationtype AS ENUM "
        "('Main', 'Summary', 'SideStory', 'AlternativeVersion')"
    )
    op.execute(
        "ALTER TABLE media ALTER COLUMN relation_type TYPE relationtype "
        "USING relation_type::text::relationtype"
    )
    op.execute("DROP TYPE relationtype_old")


def downgrade() -> None:
    # Restore 'Crossover' in its original position (between Summary and SideStory).
    op.execute("ALTER TYPE relationtype RENAME TO relationtype_old")
    op.execute(
        "CREATE TYPE relationtype AS ENUM "
        "('Main', 'Summary', 'Crossover', 'SideStory', 'AlternativeVersion')"
    )
    op.execute(
        "ALTER TABLE media ALTER COLUMN relation_type TYPE relationtype "
        "USING relation_type::text::relationtype"
    )
    op.execute("DROP TYPE relationtype_old")
