"""Retype media.age_rating to the agerating enum

Revision ID: c7e2a9f4b1d8
Revises: a9d3f6c1e2b7
Create Date: 2026-10-05 14:00:00.000000

An unmapped MAL `rating` code has been stored as None since the MAL v2
migration, so the column was already a closed set — this makes the type say so.
Values outside the labels are NULLed inside the cast so it cannot fail; on the
v0.15.6 prod data there are none.

The type is dropped first (rules/database.md). Downgrade is the plain cast back
to VARCHAR: the labels are unchanged, so nothing is lost.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c7e2a9f4b1d8"
down_revision: Union[str, None] = "a9d3f6c1e2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of AgeRating's values in declaration order — a migration must not
# import the model it outlives.
_LABELS = (
    "G - All Ages",
    "PG - Children",
    "PG-13 - Teens 13 or older",
    "R - 17+ (violence & profanity)",
    "R+ - Mild Nudity",
    "Rx - Hentai",
)


def upgrade() -> None:
    labels = ", ".join(f"'{label}'" for label in _LABELS)
    op.execute("DROP TYPE IF EXISTS agerating")
    op.execute(f"CREATE TYPE agerating AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE media ALTER COLUMN age_rating TYPE agerating "
        f"USING (CASE WHEN age_rating IN ({labels}) THEN age_rating END)::agerating"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE media ALTER COLUMN age_rating TYPE VARCHAR USING age_rating::text"
    )
    op.execute("DROP TYPE agerating")
