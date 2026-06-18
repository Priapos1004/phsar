"""Admin operations on merge candidates: list, merge, dismiss.

Merge re-parents B's media onto A, deletes B, and refreshes spoiler caches
+ A's anime embedding so the merged title is searchable. Conflict detection
is fail-loud — see MergeMalIdConflictError.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.merge_candidate_dao import MergeCandidateDAO
from app.exceptions import (
    CurationConfirmationMismatchError,
    InvalidMergeKeepError,
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
    PendingReclassification,
)
from app.seeders.split_candidate_backfiller import (
    detect_split_candidates_for_anime,
)
from app.services.anime_relation_service import (
    preview_reclassifications,
    reclassify_anime,
)
from app.services.anime_summary import summarize_anime
from app.services.merge_detection_service import detect_merge_candidates
from app.services.spoiler_service import refresh_spoiler_cache_for_anime_ids

logger = logging.getLogger(__name__)

merge_candidate_dao = MergeCandidateDAO()


_AIRED_FROM_NULL_SENTINEL = datetime.max.replace(tzinfo=timezone.utc)


def _rank_key(summary: MergeCandidateAnimeSummary, anime_id: int) -> tuple:
    """Sort key for the recommended-keep ordering: earliest aired_from
    ASC (NULL sorts last), rating_count DESC, anime_id ASC as the stable
    fallback.

    Sentinel must be tz-aware because Media.aired_from is DateTime(timezone=True);
    mixing naive datetime.max with aware values raises TypeError on comparison.
    """
    return (
        summary.earliest_aired_from or _AIRED_FROM_NULL_SENTINEL,
        -summary.rating_count,
        anime_id,
    )


async def list_pending(db: AsyncSession) -> list[MergeCandidateListItem]:
    rows = await merge_candidate_dao.list_pending_with_anime(db)
    if not rows:
        return []

    anime_ids: set[int] = set()
    for row in rows:
        anime_ids.add(row.anime_a_id)
        anime_ids.add(row.anime_b_id)
    rating_counts = await merge_candidate_dao.get_rating_counts_for_anime(db, anime_ids)

    items: list[MergeCandidateListItem] = []
    for row in rows:
        a_summary = summarize_anime(row.anime_a, rating_counts.get(row.anime_a_id, 0))
        b_summary = summarize_anime(row.anime_b, rating_counts.get(row.anime_b_id, 0))
        # Compute the preview from the unswapped pair (anime_a is the
        # survivor by convention) so the diff reflects "A absorbs B".
        # The recommended-keep swap below only affects which side
        # shows as 'A' in the card; the merge always re-parents B → A.
        pending = [
            PendingReclassification(
                media_uuid=str(media.uuid), title=media.title,
                old_relation_type=old_rt, new_relation_type=new_rt,
            )
            for media, old_rt, new_rt in preview_reclassifications(row.anime_a, row.anime_b)
        ]
        if _rank_key(a_summary, row.anime_a_id) > _rank_key(b_summary, row.anime_b_id):
            a_summary, b_summary = b_summary, a_summary
        items.append(MergeCandidateListItem(
            uuid=str(row.uuid),
            similarity_score=row.similarity_score,
            detected_by=row.detected_by,
            created_at=row.created_at,
            anime_a=a_summary,
            anime_b=b_summary,
            pending_reclassifications=pending,
        ))
    return items


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


async def list_dismissed(db: AsyncSession) -> list[MergeCandidateListItem]:
    """Dismissed pairs for the admin 'Dismissed decisions' history. Same
    summary shape as `list_pending` (so the card reuses one renderer) but
    skips the reclassification preview and the recommended-keep swap — this
    is a read-back of a past decision, not a live merge surface — and stamps
    `dismissed_at` for display/sort."""
    rows = await merge_candidate_dao.list_dismissed_with_anime(db)
    if not rows:
        return []

    anime_ids: set[int] = set()
    for row in rows:
        anime_ids.add(row.anime_a_id)
        anime_ids.add(row.anime_b_id)
    rating_counts = await merge_candidate_dao.get_rating_counts_for_anime(db, anime_ids)

    return [
        MergeCandidateListItem(
            uuid=str(row.uuid),
            similarity_score=row.similarity_score,
            detected_by=row.detected_by,
            created_at=row.created_at,
            dismissed_at=row.modified_at,
            anime_a=summarize_anime(row.anime_a, rating_counts.get(row.anime_a_id, 0)),
            anime_b=summarize_anime(row.anime_b, rating_counts.get(row.anime_b_id, 0)),
        )
        for row in rows
    ]


async def delete_decision(
    db: AsyncSession, uuid: UUID, confirm: str, username: str
) -> None:
    """Delete a DISMISSED merge candidate so the pair leaves the detector's
    skip-set and resurfaces as pending on the next detection (sweep or the
    Re-detect button). Username-gated like backup restore. Only dismissed
    rows are deletable here — pending rows belong to the live queue, and
    merged rows no longer exist (cascade-deleted with anime B)."""
    if confirm != username:
        raise CurationConfirmationMismatchError()
    candidate = await merge_candidate_dao.get_by_uuid(db, uuid)
    if candidate is None or candidate.status != MergeCandidateStatus.dismissed:
        raise MergeCandidateNotFoundError(str(uuid))
    await merge_candidate_dao.delete(db, candidate)
    await db.commit()


async def _resolve_keep_uuid(
    db: AsyncSession, keep_uuid: UUID, anime_a_id: int, anime_b_id: int
) -> int:
    """Map a kept-side UUID to the matching anime's id. Raises if the UUID
    doesn't belong to either side of this candidate — almost always a stale
    payload from the admin UI."""
    stmt = (
        select(Anime.id)
        .where(
            Anime.uuid == keep_uuid,
            Anime.id.in_([anime_a_id, anime_b_id]),
        )
    )
    keep_id = (await db.execute(stmt)).scalar_one_or_none()
    if keep_id is None:
        raise InvalidMergeKeepError(str(keep_uuid))
    return keep_id


async def merge(
    db: AsyncSession, uuid: UUID, keep_uuid: UUID | None = None
) -> str:
    """Merge the candidate's two anime. The surviving side is `keep_uuid`
    (or the table's anime_a if omitted); the other side is deleted, with
    its media re-parented onto the survivor.

    Cascade kills the candidate row + every other pending candidate that
    referenced the deleted anime on either side. Re-detection runs against
    the survivor afterwards: if the merged-in media surfaces a fresh
    similarity against some third anime that wasn't flagged before, it
    gets pushed into the queue for admin review (e.g. A-B and B-C were
    pending; merging A-B should re-evaluate A-C). Spoiler cache is
    recomputed scoped to the survivor (frontiers run per-anime, and B's
    media are now under A so that one anime covers every moved row).

    Fail-loud on shared mal_ids: per-design assumption is that Media.mal_id
    is globally unique, so the same mal_id appearing under both anime is a
    data bug that needs human review before merging.

    Returns the surviving anime's UUID.
    """
    candidate = await _ensure_pending(db, uuid)
    anime_a_id = candidate.anime_a_id
    anime_b_id = candidate.anime_b_id

    if keep_uuid is not None:
        keep_id = await _resolve_keep_uuid(db, keep_uuid, anime_a_id, anime_b_id)
        if keep_id == anime_b_id:
            anime_a_id, anime_b_id = anime_b_id, anime_a_id

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
    if anime_b is None:
        # Race window: B got deleted (and our candidate row cascade-killed)
        # between _ensure_pending and now. Surface as not-found instead of
        # letting db.delete(None) raise UnmappedInstanceError.
        raise MergeCandidateNotFoundError(str(uuid))
    await db.delete(anime_b)
    await db.flush()

    # Re-classify the consolidated media set: B's absorbed media may
    # change the canonical anchor (e.g. B's anchor is older), demote
    # weak-main media via the substance gate, or stamp alt-version
    # labels surfaced by edges that only existed once both sides
    # joined. `reclassify_anime` rewrites the umbrella row + embedding
    # in-place when drift is detected.
    anime_a = (await db.execute(
        select(Anime).where(Anime.id == anime_a_id)
        .options(selectinload(Anime.media).selectinload(Media.relation_edges))
    )).scalars().first()
    if anime_a is not None:
        await reclassify_anime(db, anime_a)
        # A merge can surface previously-dangling bridge edges that
        # connect B's media into a substance-passing chain disjoint
        # from A's main — the Dr. Stone split-merge case generalizes
        # to any consolidated graph. Detect once the survivor's
        # reclassify lands so split-candidates reflect the post-merge
        # state.
        await detect_split_candidates_for_anime(
            db, anime_a, detected_by="merge_survivor",
        )

    await db.commit()

    if anime_a is not None:
        # Re-run detection against the survivor: B's old pairs are gone, but
        # B's media is now under A and may match against a third anime that
        # didn't trigger before. seen_pairs short-circuits anything admin
        # already decided, so this only adds genuinely new candidates.
        #
        # Use SAVEPOINT instead of session.rollback(): a rollback would
        # expire `anime_a`, and the `str(anime_a.uuid)` return line below
        # would then trigger an async lazy reload → MissingGreenlet.
        try:
            async with db.begin_nested():
                await detect_merge_candidates(db, new_anime_ids=[anime_a.id])
            await db.commit()
        except Exception:
            logger.exception("Post-merge re-detection failed; merge itself succeeded")
        # Capture the survivor uuid BEFORE the recompute: that helper does a
        # per-user db.rollback() on failure, which expires every ORM instance
        # in the session (regardless of expire_on_commit=False), and reading
        # anime_a.uuid afterwards would trigger an async lazy reload →
        # MissingGreenlet. Same pre-rollback identifier-capture trap as
        # _try_step1_refresh.
        survivor_uuid = str(anime_a.uuid)
        # Spoiler cache stores media ids, not anime ids, but the frontier
        # algorithm runs per-anime. B's media were re-parented onto the
        # survivor A, so recomputing A (its media set now includes B's)
        # covers every moved row. The merge itself committed above — a
        # cache-recompute failure shouldn't 5xx the request and trick the
        # admin into retrying an already-resolved candidate. Same pattern
        # as scrape_dispatcher's post-sweep recompute.
        try:
            await refresh_spoiler_cache_for_anime_ids(db, {anime_a.id})
        except Exception:
            logger.exception("Spoiler cache recompute failed after merge")
        return survivor_uuid

    return ""
