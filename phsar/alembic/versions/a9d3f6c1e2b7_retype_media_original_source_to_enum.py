"""Retype media.original_source to the originalsource enum

Revision ID: a9d3f6c1e2b7
Revises: f5c2a8d13e96
Create Date: 2026-10-05 10:00:00.000000

An unmapped MAL `source` code used to be stored verbatim. extract_information
now stores None for it and the update sweep reports the code instead, so the
column can be a closed type. Stored rows converge to the same rule here: any
value outside the old labels — Jikan-era strings and raw codes alike — is NULLed
so the cast cannot fail.

It has to replay after restoring a dump taken before it, which is why the type is
dropped first: `pg_restore --clean` only drops what the dump contains, so the
type this revision created survives the restore orphaned, and a bare CREATE TYPE
would fail the next boot's upgrade.

The labels move from MAL's sentence case ("Light novel") to the Title Case the
other badges use ("Light Novel") inside the same cast, since it rewrites every
row anyway.

Downgrade restores the sentence-case labels, so an upgrade after it relabels
again. It is still lossy: the NULLed values are not recorded anywhere (the sweep
re-reports any code MAL still sends).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a9d3f6c1e2b7"
down_revision: Union[str, None] = "f5c2a8d13e96"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Stored label → OriginalSource's value, in declaration order. A frozen copy —
# a migration must not import the model it outlives.
_RELABEL = (
    ("Original", "Original"),
    ("Manga", "Manga"),
    ("4-koma manga", "4-Koma Manga"),
    ("Web manga", "Web Manga"),
    ("Digital manga", "Digital Manga"),
    ("Novel", "Novel"),
    ("Light novel", "Light Novel"),
    ("Web novel", "Web Novel"),
    ("Visual novel", "Visual Novel"),
    ("Game", "Game"),
    ("Card game", "Card Game"),
    ("Book", "Book"),
    ("Picture book", "Picture Book"),
    ("Radio", "Radio"),
    ("Music", "Music"),
    ("Mixed media", "Mixed Media"),
    ("Other", "Other"),
)


def upgrade() -> None:
    labels = ", ".join(f"'{new}'" for _, new in _RELABEL)
    op.execute("DROP TYPE IF EXISTS originalsource")
    op.execute(f"CREATE TYPE originalsource AS ENUM ({labels})")
    whens = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in _RELABEL)
    op.execute(
        "ALTER TABLE media ALTER COLUMN original_source TYPE originalsource "
        f"USING (CASE original_source {whens} END)::originalsource"
    )


def downgrade() -> None:
    whens = " ".join(f"WHEN '{new}' THEN '{old}'" for old, new in _RELABEL)
    op.execute(
        "ALTER TABLE media ALTER COLUMN original_source TYPE VARCHAR "
        f"USING CASE original_source::text {whens} END"
    )
    op.execute("DROP TYPE originalsource")
