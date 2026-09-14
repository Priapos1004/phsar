"""Pin stored cover_image URLs to their .webp derivative

Revision ID: e7b2d4a9f13c
Revises: c3a7e15b9d82
Create Date: 2026-09-14 12:00:00.000000

MAL v2 serves one cover under a non-deterministic extension, so every sweep
rewrote `cover_image` between the `.jpg` and `.webp` spellings of the same CDN
path and logged a diff for it — noise that drowned the sweep detail page's
change cards. `extract_information` now pins new values to `.webp`; this
converges the rows already stored, so the fix lands without one final
catalog-wide burst of phantom diffs draining over months of sweeps.

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e7b2d4a9f13c"
down_revision: Union[str, None] = "c3a7e15b9d82"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Both tables in ONE pass. `reclassify_anime` rewrites the anime row from
    # its anchor media whenever a copied field differs, so a catalog with
    # `media` converted and `anime` not would report umbrella drift on every
    # anime — and the startup relation backfill fires before the next sweep.
    #
    # The LIKE is the same anchor `_normalize_cover_url` uses: it excludes the
    # `/img/sp/icon/` placeholder one media carries, whose `.webp` is a 404.
    for table in ("media", "anime"):
        op.execute(
            rf"""
            UPDATE {table}
               SET cover_image = regexp_replace(cover_image, '\.jpg$', '.webp')
             WHERE cover_image LIKE '%/images/anime/%.jpg'
            """
        )


def downgrade() -> None:
    # Forward-only. Both spellings address the same image, and nothing records
    # which rows held which one, so a reverse rewrite would invent history —
    # and re-open the flapping this exists to stop.
    pass
