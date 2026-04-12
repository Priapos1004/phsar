"""Spoiler frontier computation with precomputed visibility cache.

Determines which media are "visible" (non-spoiler) for a user based on
their watch progress through each anime's main-story backbone.

Algorithm per anime (media sorted chronologically):
1. Extract main media (relation_type == 'main') in order.
2. No ratings → only first main media visible (or first media overall).
3. With ratings → find last rated main → next unrated main is the frontier.
4. Everything up to and including the frontier is visible.
5. Everything after the frontier is spoiler-protected.

The visibility results are stored in the `user_visible_media` table for
fast reads. The table is updated:
- Per-anime when a user rates or deletes a rating
- Full recompute for new users (seeder) and backfill on startup
"""

import logging
from collections import defaultdict
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media, RelationType
from app.models.ratings import Ratings
from app.models.user_visible_media import UserVisibleMedia
from app.schemas.rating_schema import SpoilerVisibility
from app.services.filter_service import SEASON_ORDER

logger = logging.getLogger(__name__)


class _MediaEntry(NamedTuple):
    """Lightweight media representation for frontier computation."""
    id: int
    uuid: UUID
    anime_id: int
    relation_type: str
    season_year: int | None
    season_name: str | None
    mal_id: int


def _chronological_sort_key(m: _MediaEntry) -> tuple:
    """Sort key matching anime_search_service: year → season → mal_id."""
    return (
        m.season_year or 9999,
        SEASON_ORDER.get(m.season_name or "", 0),
        m.mal_id,
    )


def compute_visible_media(
    media_by_anime: dict[int, list[_MediaEntry]],
    rated_media_ids: set[int],
) -> set[int]:
    """Pure function: compute which media IDs are visible given the frontier algorithm.

    Returns a set of media IDs that should NOT be spoiler-protected.
    """
    visible: set[int] = set()

    for _anime_id, media_list in media_by_anime.items():
        sorted_media = sorted(media_list, key=_chronological_sort_key)

        # Find main media indices in chronological order
        main_indices = [
            i for i, m in enumerate(sorted_media)
            if m.relation_type == RelationType.Main.value
        ]

        if not main_indices:
            # No main media — show only the first media
            if sorted_media:
                visible.add(sorted_media[0].id)
            continue

        # Find the frontier: the first unrated main media after the last rated main
        last_rated_main_idx = -1
        for idx in main_indices:
            if sorted_media[idx].id in rated_media_ids:
                last_rated_main_idx = idx

        if last_rated_main_idx == -1:
            # No main media rated — frontier is the first main media
            frontier_idx = main_indices[0]
        else:
            # Find the next unrated main after the last rated one
            frontier_idx = None
            for idx in main_indices:
                if idx > last_rated_main_idx and sorted_media[idx].id not in rated_media_ids:
                    frontier_idx = idx
                    break

            if frontier_idx is None:
                # All main media rated — everything is visible
                for m in sorted_media:
                    visible.add(m.id)
                continue

        # Visible: everything up to the frontier, plus any individually rated
        # media beyond it (e.g. a side story the user explicitly watched)
        for i, m in enumerate(sorted_media):
            if i <= frontier_idx or m.id in rated_media_ids:
                visible.add(m.id)

    return visible


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _fetch_media_for_anime(db: AsyncSession, anime_id: int) -> list[_MediaEntry]:
    """Fetch minimal media fields for one anime."""
    stmt = select(
        Media.id, Media.uuid, Media.anime_id, Media.relation_type,
        Media.anime_season_year, Media.anime_season_name, Media.mal_id,
    ).where(Media.anime_id == anime_id)
    result = await db.execute(stmt)
    return [_make_entry(row) for row in result.all()]


async def _fetch_all_media_lightweight(db: AsyncSession) -> list[_MediaEntry]:
    """Fetch minimal media fields for all media (used for full recompute)."""
    stmt = select(
        Media.id, Media.uuid, Media.anime_id, Media.relation_type,
        Media.anime_season_year, Media.anime_season_name, Media.mal_id,
    )
    result = await db.execute(stmt)
    return [_make_entry(row) for row in result.all()]


def _make_entry(row) -> _MediaEntry:
    return _MediaEntry(
        id=row.id,
        uuid=row.uuid,
        anime_id=row.anime_id,
        relation_type=row.relation_type.value,
        season_year=row.anime_season_year,
        season_name=row.anime_season_name.value if row.anime_season_name else None,
        mal_id=row.mal_id,
    )


async def _fetch_rated_media_ids_for_anime(db: AsyncSession, user_id: int, anime_id: int) -> set[int]:
    """Fetch rated media IDs for a user within one anime."""
    stmt = (
        select(Ratings.media_id)
        .join(Media, Ratings.media_id == Media.id)
        .where(Ratings.user_id == user_id, Media.anime_id == anime_id)
    )
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}


async def _fetch_all_rated_media_ids(db: AsyncSession, user_id: int) -> set[int]:
    """Fetch all rated media IDs for a user (used for full recompute)."""
    stmt = select(Ratings.media_id).where(Ratings.user_id == user_id)
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}


# ---------------------------------------------------------------------------
# Write: update the precomputed cache
# ---------------------------------------------------------------------------

async def recompute_visibility_for_anime(db: AsyncSession, user_id: int, anime_id: int) -> None:
    """Recompute and update visible media for one anime after a rating change.
    Does NOT commit — caller manages the transaction."""
    media_list = await _fetch_media_for_anime(db, anime_id)
    if not media_list:
        return

    rated_ids = await _fetch_rated_media_ids_for_anime(db, user_id, anime_id)
    media_by_anime = {anime_id: media_list}
    visible_ids = compute_visible_media(media_by_anime, rated_ids)

    # Delete existing rows for this user+anime's media
    anime_media_ids = [m.id for m in media_list]
    await db.execute(
        delete(UserVisibleMedia).where(
            UserVisibleMedia.user_id == user_id,
            UserVisibleMedia.media_id.in_(anime_media_ids),
        )
    )

    # Insert new visible rows
    if visible_ids:
        await db.execute(
            pg_insert(UserVisibleMedia).values(
                [{"user_id": user_id, "media_id": mid} for mid in visible_ids]
            ).on_conflict_do_nothing()
        )
    await db.flush()


async def recompute_visibility_for_user(db: AsyncSession, user_id: int) -> None:
    """Full recompute of visible media for a user. Used for new user seeding.
    Does NOT commit — caller manages the transaction."""
    all_media = await _fetch_all_media_lightweight(db)
    rated_ids = await _fetch_all_rated_media_ids(db, user_id)

    media_by_anime: dict[int, list[_MediaEntry]] = defaultdict(list)
    for m in all_media:
        media_by_anime[m.anime_id].append(m)

    visible_ids = compute_visible_media(media_by_anime, rated_ids)

    # Delete all existing rows for this user
    await db.execute(
        delete(UserVisibleMedia).where(UserVisibleMedia.user_id == user_id)
    )

    # Bulk insert
    if visible_ids:
        await db.execute(
            pg_insert(UserVisibleMedia).values(
                [{"user_id": user_id, "media_id": mid} for mid in visible_ids]
            ).on_conflict_do_nothing()
        )
    await db.flush()


# ---------------------------------------------------------------------------
# Read: query the precomputed cache
# ---------------------------------------------------------------------------

async def get_spoiler_visibility(db: AsyncSession, user_id: int) -> SpoilerVisibility:
    """Read visible media UUIDs from the precomputed cache. Fast indexed query."""
    stmt = (
        select(Media.uuid)
        .join(UserVisibleMedia, UserVisibleMedia.media_id == Media.id)
        .where(UserVisibleMedia.user_id == user_id)
    )
    result = await db.execute(stmt)
    visible_uuids = [row[0] for row in result.all()]
    return SpoilerVisibility(visible_media_uuids=visible_uuids)


async def get_visible_media_ids(db: AsyncSession, user_id: int) -> set[int]:
    """Read visible media IDs from the precomputed cache for search filtering."""
    stmt = select(UserVisibleMedia.media_id).where(UserVisibleMedia.user_id == user_id)
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}
