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
from app.models.users import RoleType, Users
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

async def _fetch_media_lightweight(
    db: AsyncSession, anime_ids: list[int] | None = None,
) -> list[_MediaEntry]:
    """Fetch the minimal media fields the frontier needs. All media when
    `anime_ids` is None (full recompute); else just those anime."""
    stmt = select(
        Media.id, Media.uuid, Media.anime_id, Media.relation_type,
        Media.anime_season_year, Media.anime_season_name, Media.mal_id,
    )
    if anime_ids is not None:
        stmt = stmt.where(Media.anime_id.in_(anime_ids))
    result = await db.execute(stmt)
    return [_make_entry(row) for row in result.all()]


async def _fetch_media_for_anime(db: AsyncSession, anime_id: int) -> list[_MediaEntry]:
    return await _fetch_media_lightweight(db, [anime_id])


async def _fetch_media_grouped_for_anime_ids(
    db: AsyncSession, anime_ids: list[int],
) -> dict[int, list[_MediaEntry]]:
    """Media for the given anime, grouped by anime_id (one read for the
    scoped post-mutation recompute)."""
    grouped: dict[int, list[_MediaEntry]] = defaultdict(list)
    for entry in await _fetch_media_lightweight(db, anime_ids):
        grouped[entry.anime_id].append(entry)
    return grouped


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

async def _replace_user_visible_media(
    db: AsyncSession,
    user_id: int,
    visible_ids: set[int],
    *,
    scope_media_ids: list[int] | None,
) -> None:
    """Delete the user's existing visibility rows, then insert `visible_ids`.
    `scope_media_ids=None` clears all of the user's rows (whole-catalog
    recompute); a list clears only rows for those media (scoped recompute,
    leaving untouched anime intact). Does NOT commit."""
    delete_stmt = delete(UserVisibleMedia).where(UserVisibleMedia.user_id == user_id)
    if scope_media_ids is not None:
        delete_stmt = delete_stmt.where(UserVisibleMedia.media_id.in_(scope_media_ids))
    await db.execute(delete_stmt)
    if visible_ids:
        await db.execute(
            pg_insert(UserVisibleMedia).values(
                [{"user_id": user_id, "media_id": mid} for mid in visible_ids]
            ).on_conflict_do_nothing()
        )
    await db.flush()


async def recompute_visibility_for_anime(db: AsyncSession, user_id: int, anime_id: int) -> None:
    """Recompute and update visible media for one anime after a rating change.
    Does NOT commit — caller manages the transaction."""
    media_list = await _fetch_media_for_anime(db, anime_id)
    if not media_list:
        return

    rated_ids = await _fetch_rated_media_ids_for_anime(db, user_id, anime_id)
    visible_ids = compute_visible_media({anime_id: media_list}, rated_ids)
    await _replace_user_visible_media(
        db, user_id, visible_ids, scope_media_ids=[m.id for m in media_list],
    )


async def recompute_visibility_for_user(db: AsyncSession, user_id: int) -> None:
    """Full recompute of visible media for a user. Used for new user seeding.
    Does NOT commit — caller manages the transaction."""
    all_media = await _fetch_media_lightweight(db)
    media_by_anime: dict[int, list[_MediaEntry]] = defaultdict(list)
    for m in all_media:
        media_by_anime[m.anime_id].append(m)
    await _recompute_user_against_catalog(db, user_id, media_by_anime)


async def refresh_spoiler_cache_for_anime_ids(
    db: AsyncSession, anime_ids: set[int] | list[int],
) -> None:
    """Recompute visibility for the given anime only, for every
    non-restricted user, after a catalog mutation touched those anime
    (new save, sweep attach, merge survivor, split source+targets).

    Scoped instead of whole-catalog because the frontier is independent
    per anime and `user_visible_media` keys on media_id: media ids only
    move *between the named anime* on merge/split, so recomputing exactly
    the affected anime is sufficient — O(users × changed) instead of
    O(users × all). Restricted users are skipped (they can't rate, pinned
    to spoiler=off, never in the cache — see _seed_user / auth_service).
    Per-user try/commit so one poisoned user doesn't abort the rest;
    `backfill_spoiler_visibility` mops up any skipped non-restricted user
    on next startup.
    """
    anime_ids = list(set(anime_ids))
    if not anime_ids:
        return
    media_by_anime = await _fetch_media_grouped_for_anime_ids(db, anime_ids)
    if not media_by_anime:
        return
    affected_media_ids = [m.id for entries in media_by_anime.values() for m in entries]

    user_ids = (
        await db.execute(
            select(Users.id).where(Users.role != RoleType.RestrictedUser)
        )
    ).scalars().all()
    for user_id in user_ids:
        try:
            await _recompute_user_for_anime_subset(
                db, user_id, media_by_anime, affected_media_ids,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                "Scoped spoiler-cache recompute failed for user %s — skipping",
                user_id,
            )


async def _recompute_user_for_anime_subset(
    db: AsyncSession,
    user_id: int,
    media_by_anime: dict[int, list[_MediaEntry]],
    affected_media_ids: list[int],
) -> None:
    """Recompute one user's visibility for just the affected anime. Rated
    ids are restricted to `affected_media_ids` (the frontier of each anime
    consults only ratings on that anime's media), and the delete+reinsert
    is keyed on the same set so untouched anime's cache rows are left
    intact."""
    rated_stmt = select(Ratings.media_id).where(
        Ratings.user_id == user_id, Ratings.media_id.in_(affected_media_ids),
    )
    rated_ids = {row[0] for row in (await db.execute(rated_stmt)).all()}
    visible_ids = compute_visible_media(media_by_anime, rated_ids)
    await _replace_user_visible_media(
        db, user_id, visible_ids, scope_media_ids=affected_media_ids,
    )


async def _recompute_user_against_catalog(
    db: AsyncSession,
    user_id: int,
    media_by_anime: dict[int, list[_MediaEntry]],
) -> None:
    """Single full-recompute worker for one user against a whole-catalog
    snapshot. Used by `recompute_visibility_for_user` (new-user seeding /
    startup backfill), which builds the snapshot itself."""
    rated_ids = await _fetch_all_rated_media_ids(db, user_id)
    visible_ids = compute_visible_media(media_by_anime, rated_ids)
    await _replace_user_visible_media(db, user_id, visible_ids, scope_media_ids=None)


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
