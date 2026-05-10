"""Admin operations on merge candidates: list, merge, dismiss.

Merge re-parents B's media onto A, deletes B, and refreshes spoiler caches
+ A's anime embedding so the merged title is searchable. Conflict detection
is fail-loud — see MergeMalIdConflictError.
"""

import logging
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.merge_candidate_dao import MergeCandidateDAO
from app.exceptions import (
    MergeCandidateAlreadyResolvedError,
    MergeCandidateNotFoundError,
    MergeMalIdConflictError,
)
from app.models.anime import Anime
from app.models.media import Media
from app.models.merge_candidate import MergeCandidate, MergeCandidateStatus
from app.schemas.admin_schema import (
    MergeCandidateAnimeSummary,
    MergeCandidateListItem,
)
from app.services.anime_search_service import anime_title_texts
from app.services.spoiler_service import refresh_spoiler_cache_for_all_users
from app.services.vector_embedding_service import create_anime_embedding

logger = logging.getLogger(__name__)

merge_candidate_dao = MergeCandidateDAO()


def _summarize(anime: Anime) -> MergeCandidateAnimeSummary:
    studio_names: set[str] = set()
    years: list[int] = []
    for media in anime.media:
        for ms in media.media_studio:
            studio_names.add(ms.studio.name)
        if media.anime_season_year is not None:
            years.append(media.anime_season_year)
    return MergeCandidateAnimeSummary(
        uuid=str(anime.uuid),
        title=anime.title,
        name_eng=anime.name_eng,
        name_jap=anime.name_jap,
        media_count=len(anime.media),
        studios=sorted(studio_names),
        earliest_year=min(years) if years else None,
    )


async def list_pending(db: AsyncSession) -> list[MergeCandidateListItem]:
    rows = await merge_candidate_dao.list_pending_with_anime(db)
    return [
        MergeCandidateListItem(
            uuid=str(row.uuid),
            similarity_score=row.similarity_score,
            detected_by=row.detected_by,
            created_at=row.created_at,
            anime_a=_summarize(row.anime_a),
            anime_b=_summarize(row.anime_b),
        )
        for row in rows
    ]


async def _ensure_pending(db: AsyncSession, uuid: UUID) -> MergeCandidate:
    candidate = await merge_candidate_dao.get_by_uuid(db, uuid)
    if candidate is None:
        raise MergeCandidateNotFoundError(str(uuid))
    if candidate.status != MergeCandidateStatus.pending:
        raise MergeCandidateAlreadyResolvedError(candidate.status.value)
    return candidate


async def dismiss(db: AsyncSession, uuid: UUID) -> None:
    """Mark a candidate as reviewed-but-not-merged. No DB mutation otherwise."""
    candidate = await _ensure_pending(db, uuid)
    candidate.status = MergeCandidateStatus.dismissed
    await db.commit()


async def merge(db: AsyncSession, uuid: UUID) -> str:
    """Merge anime_b into anime_a:
    - Re-parent all of B's media rows to A
    - Re-link studios accumulated only on B (so search filters keep working)
    - Delete B (cascades anime_search, anime relationships)
    - Refresh A's anime embedding to reflect any new titles in the merged
      media list
    - Recompute spoiler cache for all users so the merged anime's frontier
      uses the combined media set

    Returns the surviving anime's UUID.

    Fail-loud on shared mal_ids: per-design assumption is that Media.mal_id
    is globally unique, so the same mal_id appearing under both anime is a
    data bug that needs human review before merging.
    """
    candidate = await _ensure_pending(db, uuid)
    anime_a_id = candidate.anime_a_id
    anime_b_id = candidate.anime_b_id

    # Pre-flight: detect shared mal_ids before mutating anything.
    a_mal_ids_stmt = select(Media.mal_id).where(Media.anime_id == anime_a_id)
    b_mal_ids_stmt = select(Media.mal_id).where(Media.anime_id == anime_b_id)
    a_mal_ids = set((await db.execute(a_mal_ids_stmt)).scalars().all())
    b_mal_ids = set((await db.execute(b_mal_ids_stmt)).scalars().all())
    overlap = a_mal_ids & b_mal_ids
    if overlap:
        raise MergeMalIdConflictError(next(iter(overlap)))

    # Re-parent B's media to A.
    await db.execute(
        update(Media).where(Media.anime_id == anime_b_id).values(anime_id=anime_a_id)
    )
    await db.flush()

    # Drop B. ON DELETE CASCADE on merge_candidates.anime_b_id removes this
    # candidate row + any other pending candidates referencing B in the same
    # statement, so we don't update candidate.status here — the row no longer
    # exists once the cascade fires.
    anime_b = await db.get(Anime, anime_b_id)
    await db.delete(anime_b)
    await db.flush()

    # Refresh A's title embedding from the merged media list (B's titles may
    # have surfaced romanizations A didn't have). Drop the old AnimeSearch
    # row first since create_anime_embedding inserts a fresh row.
    anime_a_stmt = (
        select(Anime)
        .where(Anime.id == anime_a_id)
        .options(selectinload(Anime.anime_search))
    )
    anime_a = (await db.execute(anime_a_stmt)).scalars().first()
    if anime_a is not None and anime_a.anime_search is not None:
        await db.delete(anime_a.anime_search)
        await db.flush()
    if anime_a is not None:
        await create_anime_embedding(
            db,
            anime_id=anime_a.id,
            title_texts=anime_title_texts(anime_a),
            description_text=anime_a.description or "",
        )

    await db.commit()

    if anime_a is not None:
        # Spoiler cache stores media ids, not anime ids, but the frontier
        # algorithm runs per-anime. Recompute globally so frontiers reflect
        # the merged media list.
        await refresh_spoiler_cache_for_all_users(db)

    return str(anime_a.uuid) if anime_a else ""
