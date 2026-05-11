"""Clear media_unwanted reason=Unknown entries

Revision ID: 2f1a8e3c4d5b
Revises: cb6055f6a525
Create Date: 2026-05-10 19:50:00.000000

Pre-7c, JikanScraper.search_title blacklisted any anime whose MAL
response had `media_type=None` with reason='Unknown'. Most of these are
not-yet-aired shows that MAL hasn't categorized yet — once they air and
get a real media_type, the unwanted entry permanently prevents
rediscovery. 7c stops creating those entries; this migration clears the
backlog so the next sweep can pick them up via the relations probe.

"""
from typing import Sequence, Union

from alembic import op


revision: str = "2f1a8e3c4d5b"
down_revision: Union[str, None] = "cb6055f6a525"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM media_unwanted WHERE reason = 'Unknown'")


def downgrade() -> None:
    # Forward-only data delete — there's no record of which mal_ids were
    # in the table before, so downgrade can't restore them.
    pass
