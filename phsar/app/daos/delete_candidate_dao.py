from collections.abc import Collection, Sequence
from uuid import UUID

from sqlalchemy import ColumnExpressionArgument, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import recency_order
from app.daos.base_mal_id_dao import MalIdDAO
from app.models.delete_candidate import DeleteCandidate, DeleteCandidateStatus
from app.models.media import Media
from app.models.ratings import Ratings
from app.models.watchlist import Watchlist
from app.services.relation_classifier import AIRING_STATUS_FINISHED_AIRING

# Detection thresholds for the low-signal pass. Hardcoded rather than settings:
# the admin reviews every row this raises, so a wrong threshold only changes how
# many rows there are to dismiss — it cannot do damage, and a knob nobody turns
# costs API surface and a config line for nothing.
#
# MAL withholds the published mean below its own vote floor, so `score IS NULL`
# and a low `scored_by` are nearly the same predicate; both are applied because
# the overlap is not exact (a handful of rows clear the vote bar with no mean).
LOW_SIGNAL_MAX_SCORED_BY = 50

# How long an entry gets to find an audience before its vote count means
# anything. A show that aired last season has barely been seen — MAL votes
# accumulate for months after a premiere, so flagging a recent one reads its
# emptiness as a verdict when it is really just earliness. A year is past the
# point where a genuinely watched title would still be at single-digit votes.
#
# It also keeps the queue honest about what it is for: entries that never found
# an audience, not entries that have not had the chance to.
LOW_SIGNAL_MIN_AGE_YEARS = 1


class DeleteCandidateDAO(MalIdDAO[DeleteCandidate]):
    """`MalIdDAO`, not plain `BaseDAO`: the row's identity snapshot carries a
    `mal_id`, so the base class's `get_by_mal_id` serves the 404 detector's
    any-status check for free — the same base `MediaUnwantedDAO`, `MediaDAO` and
    `AnimeDAO` sit on.

    That check is what makes a dismissal stick — the pending index is partial, so
    nothing else stops the next 404 re-raising a row an admin chose to keep.
    """

    def __init__(self):
        super().__init__(DeleteCandidate)

    async def get_by_uuid(self, db: AsyncSession, uuid: UUID) -> DeleteCandidate | None:
        return await self.get_by_field(db, uuid=uuid)

    async def count_pending(self, db: AsyncSession) -> int:
        """Cheap status='pending' count for the admin bell's pinned reminder,
        polled every tick while an admin is logged in. Mirrors the merge and
        split counters; the partial index bounds the cardinality."""
        stmt = (
            select(func.count(DeleteCandidate.id))
            .where(DeleteCandidate.status == DeleteCandidateStatus.pending)
        )
        return (await db.execute(stmt)).scalar_one()

    async def list_pending_with_media(self, db: AsyncSession) -> list[DeleteCandidate]:
        """Pending candidates, FIFO with the PK tiebreak that makes it actually
        first-in — the backfill inserts its whole batch in one transaction, so
        every row shares a `created_at` and the queue would otherwise reshuffle
        between refreshes."""
        return await self._list_with_media(
            db,
            DeleteCandidateStatus.pending,
            (DeleteCandidate.created_at.asc(), DeleteCandidate.id.asc()),
        )

    async def list_dismissed_with_media(self, db: AsyncSession) -> list[DeleteCandidate]:
        """DISMISSED candidates for the 'Dismissed decisions' history, newest
        dismissal first (dismissing flips status + commits, bumping
        `modified_at`). Deleted rows aren't here: `dismissed` is the only
        resurrectable state, and hard-deleting one drops its mal_id from the
        skip-set so detection resurfaces it."""
        return await self._list_with_media(
            db, DeleteCandidateStatus.dismissed, recency_order(DeleteCandidate)
        )

    async def _list_with_media(
        self,
        db: AsyncSession,
        status: DeleteCandidateStatus,
        order_by: tuple[ColumnExpressionArgument, ...],
    ) -> list[DeleteCandidate]:
        """Shared query for both lists.

        Loads the media and its parent anime, but deliberately NOT the parent's
        sibling media: the card needs only how many there are, and hydrating a
        long-running franchise's full media set — synopses included — to call
        `len()` on it would put dozens of rows on the wire per candidate. The
        count comes from `get_franchise_sizes` instead.

        `media` is legitimately None on a resolved row (ON DELETE SET NULL), so
        every consumer must treat the snapshot columns as the source of truth
        and the relationship as extra detail when it happens to still exist.
        """
        stmt = (
            select(DeleteCandidate)
            .where(DeleteCandidate.status == status)
            .options(selectinload(DeleteCandidate.media).selectinload(Media.anime))
            .order_by(*order_by)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def upsert_pending(
        self,
        db: AsyncSession,
        media_rows: Sequence[Media],
        detected_by: str,
    ) -> int:
        """Insert a pending candidate per media, ignoring any already live.
        Returns how many rows landed, so the sweep can report what it raised.

        ONE multi-row INSERT rather than a round trip per media: the first pass
        over a never-flagged catalogue — the case the backfill endpoint exists
        for after a restore — is otherwise hundreds of sequential statements
        inside the maintenance window.

        ON CONFLICT targets the PARTIAL unique index, so re-detecting a mal_id
        while a candidate is already pending is a no-op, while one that was
        dismissed and later hard-deleted can be raised again.

        The identity snapshot is copied in here rather than read back later:
        after the delete the media row is gone and these columns are all that
        remains of it.
        """
        if not media_rows:
            return 0
        stmt = (
            pg_insert(DeleteCandidate)
            .values([
                {
                    "media_id": m.id,
                    "mal_id": m.mal_id,
                    "title": m.title,
                    "name_eng": m.name_eng,
                    "name_jap": m.name_jap,
                    "detected_by": detected_by,
                    "status": DeleteCandidateStatus.pending,
                }
                for m in media_rows
            ])
            .on_conflict_do_nothing(
                index_elements=["mal_id"],
                index_where=text("status = 'pending'"),
            )
            .returning(DeleteCandidate.id)
        )
        return len((await db.execute(stmt)).all())

    async def get_user_reference_counts(
        self, db: AsyncSession, media_ids: Collection[int]
    ) -> dict[int, tuple[int, int]]:
        """`{media_id: (rating_count, watchlist_count)}` — what a user loses if
        this media is deleted.

        Deleting a media cascades to everything keyed on it, so this is the
        pre-flight the confirm dialog renders — the two counts a user would
        actually notice losing. Media with no references are absent; caller
        defaults to (0, 0).

        TWO grouped queries merged in Python, not correlated scalar subqueries
        in one SELECT: neither table has an index leading with `media_id`
        (both carry `(user_id, media_id)`), so a correlated subquery is planned
        as a SubPlan per outer row and each execution seq-scans the whole table.
        Two statements scan each table once regardless of queue length. They
        also cannot be one query — joining both multiplies the rows and each
        count comes out as the product.
        """
        if not media_ids:
            return {}
        counts: dict[int, tuple[int, int]] = {}
        for position, model in ((0, Ratings), (1, Watchlist)):
            stmt = (
                select(model.media_id, func.count(model.id))
                .where(model.media_id.in_(media_ids))
                .group_by(model.media_id)
            )
            for media_id, count in (await db.execute(stmt)).all():
                existing = counts.get(media_id, (0, 0))
                counts[media_id] = (
                    (count, existing[1]) if position == 0 else (existing[0], count)
                )
        return counts

    async def get_franchise_sizes(
        self, db: AsyncSession, anime_ids: Collection[int]
    ) -> dict[int, int]:
        """`{anime_id: media_count}` — the franchise context the card renders.

        One grouped count for the whole page, rather than eager-loading every
        sibling media row just to take its length. Anime absent from the result
        have no media; caller defaults to 0.
        """
        if not anime_ids:
            return {}
        stmt = (
            select(Media.anime_id, func.count(Media.id))
            .where(Media.anime_id.in_(anime_ids))
            .group_by(Media.anime_id)
        )
        return dict((await db.execute(stmt)).all())

    async def select_low_signal_media(self, db: AsyncSession) -> list[Media]:
        """Standalone entries that never gained MAL traction — the `low_signal`
        detector's input.

        "Standalone" is the gate that matters, and it is why this is not simply
        "every media with no score". Plenty of legitimate franchises carry an
        unrated OVA or special; those are side-entries of something real and
        must not be flagged. An anime whose ONLY media never drew votes is the
        seasonal sweep having picked up noise.

        `Finished Airing` excludes the far larger not-yet-aired cohort, which has
        no score for the obvious reason and would swamp the queue.

        The age floor is what stops the pass reading "too new to have votes" as
        "nobody wants this" — see `LOW_SIGNAL_MIN_AGE_YEARS`. An **undated**
        media falls out with it, because a NULL `aired_from` fails the
        comparison: we cannot age it, and proposing deletion is the wrong place
        to guess. Same shape as the sweep's long-tail window, where an undated
        media also lands on the conservative side of the CASE.

        Already-seen mal_ids are excluded by a NOT EXISTS against
        `delete_candidates` rather than a bind list of ids fetched up front: the
        set of resolved candidates only grows, and passing it as `NOT IN` would
        grow the statement's parameter list with it forever.
        """
        solo = (
            select(Media.anime_id)
            .group_by(Media.anime_id)
            .having(func.count(Media.id) == 1)
            .scalar_subquery()
        )
        already_seen = (
            select(DeleteCandidate.id)
            .where(DeleteCandidate.mal_id == Media.mal_id)
            .correlate(Media)
            .exists()
        )
        stmt = (
            select(Media)
            .where(
                Media.anime_id.in_(solo),
                Media.score.is_(None),
                Media.scored_by < LOW_SIGNAL_MAX_SCORED_BY,
                Media.airing_status == AIRING_STATUS_FINISHED_AIRING,
                Media.aired_from
                < func.now() - text(f"interval '{LOW_SIGNAL_MIN_AGE_YEARS} years'"),
                ~already_seen,
            )
            .order_by(Media.scored_by.asc(), Media.id.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
