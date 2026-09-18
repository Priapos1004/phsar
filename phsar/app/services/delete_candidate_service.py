"""Admin operations on delete candidates: list, dismiss, remove.

Nothing here runs unattended, and removal is media-grained rather than
anime-grained. Both are argued in `docs/features/curation.md`.
"""

import logging
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.delete_candidate_dao import DeleteCandidateDAO
from app.exceptions import (
    CurationConfirmationMismatchError,
    DeleteCandidateAlreadyResolvedError,
    DeleteCandidateNotFoundError,
)
from app.models.anime import Anime
from app.models.delete_candidate import DeleteCandidate, DeleteCandidateStatus
from app.models.media import Media
from app.schemas.admin_schema import DeleteCandidateListItem
from app.services.anime_relation_service import reclassify_anime
from app.services.spoiler_service import refresh_spoiler_cache_for_anime_ids
from app.services.unwanted_media_service import create_unwanted_media

logger = logging.getLogger(__name__)

delete_candidate_dao = DeleteCandidateDAO()

DETECTED_BY_SWEEP_404 = "sweep_404"
DETECTED_BY_LOW_SIGNAL = "low_signal"

# Goes into `media_unwanted.reason`, which is String(20) — anything longer is
# silently a migration. It also surfaces verbatim to users in
# AnimeFilteredOutError ("'X' was filtered out as Admin curation and not added
# to the catalog"), so it has to read as a sentence fragment.
BLACKLIST_REASON = "Admin curation"


async def _ensure_pending(db: AsyncSession, uuid: UUID) -> DeleteCandidate:
    candidate = await delete_candidate_dao.get_by_uuid(db, uuid)
    if candidate is None:
        raise DeleteCandidateNotFoundError(str(uuid))
    if candidate.status != DeleteCandidateStatus.pending:
        raise DeleteCandidateAlreadyResolvedError(candidate.status.value)
    return candidate


def _build_list_item(
    row: DeleteCandidate,
    counts: dict[int, tuple[int, int]],
    franchise_sizes: dict[int, int],
    *,
    dismissed: bool,
) -> DeleteCandidateListItem:
    """Row → DTO, shared by the pending and dismissed lists.

    Everything reads from the snapshot columns first. `row.media` is legitimately
    None on a resolved row (ON DELETE SET NULL), so the live-media fields are
    extras, not the identity.
    """
    media = row.media
    anime = media.anime if media is not None else None
    ratings, watchlist = counts.get(media.id, (0, 0)) if media is not None else (0, 0)
    return DeleteCandidateListItem(
        uuid=str(row.uuid),
        detected_by=row.detected_by,
        created_at=row.created_at,
        dismissed_at=row.modified_at if dismissed else None,
        mal_id=row.mal_id,
        title=row.title,
        name_eng=row.name_eng,
        name_jap=row.name_jap,
        media_uuid=str(media.uuid) if media is not None else None,
        anime_title=anime.title if anime is not None else None,
        anime_media_count=franchise_sizes.get(anime.id, 0) if anime is not None else 0,
        # A sweep_404 row's last-known vote count describes an entry that no
        # longer exists upstream, so it would only mislead. Only the low-signal
        # detector's own evidence is worth showing.
        scored_by=(
            media.scored_by
            if media is not None and row.detected_by == DETECTED_BY_LOW_SIGNAL
            else None
        ),
        media_type=media.media_type.value if media is not None else None,
        rating_count=ratings,
        watchlist_count=watchlist,
    )


async def _list(db: AsyncSession, *, dismissed: bool) -> list[DeleteCandidateListItem]:
    rows = (
        await delete_candidate_dao.list_dismissed_with_media(db)
        if dismissed
        else await delete_candidate_dao.list_pending_with_media(db)
    )
    if not rows:
        return []
    media_ids = {row.media_id for row in rows if row.media_id is not None}
    anime_ids = {
        row.media.anime_id for row in rows if row.media is not None
    }
    counts = await delete_candidate_dao.get_user_reference_counts(db, media_ids)
    sizes = await delete_candidate_dao.get_franchise_sizes(db, anime_ids)
    return [
        _build_list_item(row, counts, sizes, dismissed=dismissed) for row in rows
    ]


async def list_pending(db: AsyncSession) -> list[DeleteCandidateListItem]:
    """The live queue."""
    return await _list(db, dismissed=False)


async def list_dismissed(db: AsyncSession) -> list[DeleteCandidateListItem]:
    """Past keep-it decisions, for the admin 'Dismissed decisions' history."""
    return await _list(db, dismissed=True)


async def dismiss(db: AsyncSession, uuid: UUID) -> None:
    """Mark a candidate as reviewed-and-kept. No other DB mutation.

    The row itself is the suppression: both detectors skip any mal_id carrying a
    live decision, so this holds until the dismissal is explicitly deleted.
    """
    candidate = await _ensure_pending(db, uuid)
    candidate.status = DeleteCandidateStatus.dismissed
    await db.commit()


async def delete_decision(db: AsyncSession, uuid: UUID) -> None:
    """Delete a DISMISSED candidate so its mal_id leaves the detectors' skip-set
    and resurfaces on the next detection. Only dismissed rows are deletable —
    pending rows belong to the live queue, and a deleted row is the audit record
    of a removal, which must not be erasable from the UI.

    Not username-gated — see the confirm tiers in `.claude/rules/frontend.md`."""
    candidate = await delete_candidate_dao.get_by_uuid(db, uuid)
    if candidate is None or candidate.status != DeleteCandidateStatus.dismissed:
        raise DeleteCandidateNotFoundError(str(uuid))
    await delete_candidate_dao.delete(db, candidate)
    await db.commit()


async def remove(
    db: AsyncSession, uuid: UUID, *, confirm: str, username: str, blacklist: bool
) -> None:
    """Delete the candidate's media, and its anime if that was the last one.

    Ordering is load-bearing:

    1. Blacklist BEFORE the delete. `media_unwanted` has no FK to media, so the
       row survives the cascade — the same reason `_remove_hentai_anime` does it
       in this order.
    2. Snapshot anything needed afterwards. The delete expires the ORM
       attributes, so reading `media.title` after it raises MissingGreenlet.
    3. Core `delete(Media)`, never `db.delete(media)`. Every relationship is
       `lazy="raise"`, so the ORM cascade would try to lazy-load the children it
       wants to delete and trip the guard. The DB-level ON DELETE CASCADE does
       that work instead — and it is what takes the user's data with it.
    4. Reclassify a surviving anime. The deleted media may have been the anchor,
       and `anime.mal_id` tracks the anchor's mal_id — skipping this leaves the
       umbrella pointing at a row that no longer exists.

    5. Recompute a surviving anime's spoiler cache, after the commit.

    Orphaned studio rows are left to the sweep's existing `delete_orphaned`
    pass rather than duplicated here.
    """
    if confirm != username:
        raise CurationConfirmationMismatchError()
    candidate = await _ensure_pending(db, uuid)

    # `media_id` is already None when the media was removed by some other path
    # (a merge, the hentai sweep, a script) without this candidate being
    # resolved. There is then nothing to delete, but the decision still gets
    # recorded — including the blacklist, which keys on the snapshot mal_id and
    # so works with or without the row.
    media = (
        # Only the parent is loaded, not its media collection. Loading it here
        # would put every sibling into the identity map WITHOUT their
        # relation_edges, and the reclassify query below would then skip its own
        # nested loader for an already-loaded collection and trip lazy="raise"
        # inside the classifier.
        await db.execute(
            select(Media)
            .where(Media.id == candidate.media_id)
            .options(selectinload(Media.anime))
        )
    ).scalars().first() if candidate.media_id is not None else None

    # The snapshot is the fallback identity; a live row's title is preferred
    # because MAL may have renamed it since detection.
    mal_id = media.mal_id if media is not None else candidate.mal_id
    title = media.title if media is not None else candidate.title
    ratings = watchlist = 0
    remaining: int | None = None
    anime_id: int | None = None

    if blacklist:
        await create_unwanted_media(db, {(mal_id, title, BLACKLIST_REASON)})

    if media is not None:
        anime_id = media.anime.id
        media_id = media.id
        # Counted before the delete, purely so the log line says what was
        # destroyed. Nothing else in the codebase records this.
        counts = await delete_candidate_dao.get_user_reference_counts(db, [media_id])
        ratings, watchlist = counts.get(media_id, (0, 0))

        await db.execute(delete(Media).where(Media.id == media_id))

        remaining = await db.scalar(
            select(func.count(Media.id)).where(Media.anime_id == anime_id)
        )
        if remaining == 0:
            # Empty umbrella. Nothing in the catalogue holds an anime with no
            # media, and search/filters would surface it as a ghost row.
            await db.execute(delete(Anime).where(Anime.id == anime_id))
        else:
            # populate_existing: the deleted media is still sitting in this
            # session's collection for `anime`, and without it SQLAlchemy leaves
            # an already-loaded collection alone — so the classifier would be
            # handed a media set containing a row that no longer exists, and the
            # nested relation_edges loader would never run.
            surviving = (
                await db.execute(
                    select(Anime)
                    .where(Anime.id == anime_id)
                    .options(
                        selectinload(Anime.media).options(
                            selectinload(Media.relation_edges),
                        )
                    )
                    .execution_options(populate_existing=True)
                )
            ).scalars().first()
            if surviving is not None:
                await reclassify_anime(db, surviving)

    candidate.status = DeleteCandidateStatus.deleted
    candidate.blacklisted = blacklist
    # Set explicitly rather than leaving it to the FK's ON DELETE SET NULL. The
    # DB does the right thing either way, but sessions here run with
    # expire_on_commit=False, so the ORM would otherwise keep serving a
    # media_id pointing at a row that no longer exists. The FK action stays the
    # backstop for media deleted by any other path.
    candidate.media_id = None
    await db.commit()

    # Only when the anime survived — an emptied one had its cache rows taken by the
    # cascade, which is why `_remove_hentai_anime` skips this entirely.
    # Post-commit and soft, like merge and split: the deletion is already durable,
    # and a recompute failure must not 5xx an admin into retrying a resolved
    # candidate. The nightly sweep's recompute is the backstop.
    if remaining:
        try:
            await refresh_spoiler_cache_for_anime_ids(db, {anime_id})
        except Exception:
            logger.exception("Spoiler cache recompute failed after curation delete")

    logger.info(
        "Deleted media mal_id=%s (%s) via curation — blacklisted=%s, "
        "anime %s, destroyed %s ratings + %s watchlist entries",
        mal_id, title, blacklist,
        "already gone" if remaining is None
        else "removed (last media)" if remaining == 0 else "kept",
        ratings, watchlist,
    )


async def detect_low_signal_candidates(db: AsyncSession) -> int:
    """Raise a candidate for every standalone entry that never gained MAL
    traction. Returns how many were newly raised. Caller commits.

    Idempotent twice over: the query's NOT EXISTS skips any mal_id carrying a
    live decision, and the partial unique index catches a racer.
    """
    inserted = await delete_candidate_dao.upsert_pending(
        db,
        await delete_candidate_dao.select_low_signal_media(db),
        DETECTED_BY_LOW_SIGNAL,
    )
    if inserted:
        logger.info("Low-signal detection raised %s delete candidate(s)", inserted)
    return inserted


async def raise_sweep_404_candidate(db: AsyncSession, media: Media) -> bool:
    """Raise a candidate for a media MAL returned 404 for. Returns whether one
    landed. Caller commits.

    The live-decision lookup is not redundant with the insert's ON CONFLICT: that
    index is partial on `status = 'pending'`, so it would happily add a second
    pending row for a mal_id an admin had already dismissed. This is what makes
    that dismissal stick against a nightly 404.
    """
    if await delete_candidate_dao.has_live_decision(db, media.mal_id):
        return False
    return await delete_candidate_dao.upsert_pending(
        db, [media], DETECTED_BY_SWEEP_404
    ) > 0
