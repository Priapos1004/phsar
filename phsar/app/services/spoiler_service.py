"""Spoiler frontier computation with precomputed visibility cache.

Determines which media are "visible" (non-spoiler) for a user based on
their watch progress through each anime's main-story backbone.

Algorithm per anime (media sorted chronologically):
1. Extract anchor media (relation_type ∈ {'main', 'alternative_version'})
   in order. Alternative versions count as anchors because retellings
   like Evangelion's Rebuild Movies extend the story — a user who
   watched the 1995 TV shouldn't have Rebuild Movie 4 (a different
   ending) unblurred, but Movie 1 (an early retelling) is fair game.
2. No ratings → only first anchor visible (or first media overall).
3. With ratings → find last rated anchor → next unrated anchor is the
   frontier.
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
from app.models.users import Users
from app.schemas.rating_schema import SpoilerVisibility
from app.services.filter_service import chronological_media_key

logger = logging.getLogger(__name__)


# Relation types that act as spoiler-frontier anchors. `main` is the
# canonical backbone; `alternative_version` covers retellings that
# extend or diverge from the canonical story (Evangelion Rebuild
# Movies, Hokuto no Ken alts) so each gates the next.
_ANCHOR_TYPES = frozenset({
    RelationType.Main.value,
    RelationType.AlternativeVersion.value,
})


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
    """Thin adapter over `chronological_media_key` for the local `_MediaEntry`
    projection — keeps the frontier walk in lockstep with anime_search_service
    and media_search_service via the shared helper."""
    return chronological_media_key(m.season_year, m.season_name, m.mal_id)


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

        # Anchor indices: main + alternative_version, in air-date order.
        anchor_indices = [
            i for i, m in enumerate(sorted_media)
            if m.relation_type in _ANCHOR_TYPES
        ]

        if not anchor_indices:
            # No anchor media — show only the first media.
            if sorted_media:
                visible.add(sorted_media[0].id)
            continue

        last_rated_anchor_idx = -1
        for idx in anchor_indices:
            if sorted_media[idx].id in rated_media_ids:
                last_rated_anchor_idx = idx

        if last_rated_anchor_idx == -1:
            frontier_idx = anchor_indices[0]
        else:
            frontier_idx = None
            for idx in anchor_indices:
                if idx > last_rated_anchor_idx and sorted_media[idx].id not in rated_media_ids:
                    frontier_idx = idx
                    break

            if frontier_idx is None:
                # All anchors rated — everything is visible.
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
    media_by_anime: dict[int, list[_MediaEntry]] = defaultdict(list)
    for m in all_media:
        media_by_anime[m.anime_id].append(m)
    await _recompute_user_against_catalog(db, user_id, media_by_anime)


async def refresh_spoiler_cache_for_all_users(db: AsyncSession) -> None:
    """Recompute every user's visibility cache after a catalog mutation
    (new save, anime merge). Per-user try/commit so one poisoned user
    (e.g. FK pointing at a stale rating row) doesn't abort the rest and
    doesn't unwind already-committed catalog rows. backfill_spoiler_visibility
    will mop up anyone we skip on next startup.

    The catalog-wide media read is hoisted out of the per-user loop:
    `_fetch_all_media_lightweight` returns the same rows regardless of
    user, so calling `recompute_visibility_for_user` per user would ship
    O(users × media) rows for nothing. Hoisting cuts the post-sweep
    recompute (the longest single phase of the maintenance window)
    proportionally to user count.
    """
    all_media = await _fetch_all_media_lightweight(db)
    media_by_anime: dict[int, list[_MediaEntry]] = defaultdict(list)
    for m in all_media:
        media_by_anime[m.anime_id].append(m)

    user_ids = (await db.execute(select(Users.id))).scalars().all()
    for user_id in user_ids:
        try:
            await _recompute_user_against_catalog(db, user_id, media_by_anime)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                "Spoiler-cache recompute failed for user %s — skipping",
                user_id,
            )


async def _recompute_user_against_catalog(
    db: AsyncSession,
    user_id: int,
    media_by_anime: dict[int, list[_MediaEntry]],
) -> None:
    """Single full-recompute worker. The all-users refresh shares one
    catalog snapshot across users; the single-user refresh
    (`recompute_visibility_for_user`) builds the snapshot itself and
    delegates here."""
    rated_ids = await _fetch_all_rated_media_ids(db, user_id)
    visible_ids = compute_visible_media(media_by_anime, rated_ids)

    await db.execute(
        delete(UserVisibleMedia).where(UserVisibleMedia.user_id == user_id)
    )
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
