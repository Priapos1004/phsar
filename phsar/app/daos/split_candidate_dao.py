"""DAO for SplitCandidate — admin queue surfacing disjoint-franchise
contamination flagged by `find_disjoint_franchises`.

Sibling to MergeCandidateDAO. The interface mirrors merge_candidate's
admin workflow (`upsert_pending` / `list_pending_with_anime` / `get_by_uuid`)
but the table shape is asymmetric — one anime + JSONB clusters payload —
so the queries don't share a base.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.anime import Anime
from app.models.media import Media
from app.models.media_studio import MediaStudio
from app.models.split_candidate import SplitCandidate, SplitCandidateStatus


def _cluster_signature(clusters: list[dict]) -> list[list[int]]:
    """Sorted-cluster-mal_id-lists as the natural key for idempotent
    detection. If a re-run produces the same clusters (same anime, same
    mal_ids per cluster), the existing pending row stands — no
    duplicate. If the payload changes (new media absorbed into the
    contaminated row since last detection), it's a different signature
    and the caller decides whether to supersede.
    """
    return sorted(sorted(c["member_mal_ids"]) for c in clusters)


class SplitCandidateDAO(BaseDAO[SplitCandidate]):
    def __init__(self):
        super().__init__(SplitCandidate)

    async def get_by_uuid(
        self, db: AsyncSession, uuid: UUID
    ) -> SplitCandidate | None:
        stmt = select(SplitCandidate).where(SplitCandidate.uuid == uuid)
        return (await db.execute(stmt)).scalars().first()

    async def count_pending(self, db: AsyncSession) -> int:
        """Cheap status='pending' count for the admin bell's pinned
        reminder — paired with MergeCandidateDAO.count_pending. Sub-
        millisecond on the small pending set."""
        stmt = (
            select(func.count(SplitCandidate.id))
            .where(SplitCandidate.status == SplitCandidateStatus.pending)
        )
        return (await db.execute(stmt)).scalar_one()

    async def list_pending_with_anime(
        self, db: AsyncSession
    ) -> list[SplitCandidate]:
        """List pending candidates with the source anime + media +
        relation-edge sidecars + media studios eagerly loaded. Admin UI
        needs media titles, types, sidecars (for cluster previews) AND
        studios (for the source-anime card summary), so all of this
        rides one roundtrip."""
        media_loader = selectinload(Anime.media).options(
            selectinload(Media.relation_edges),
            selectinload(Media.media_studio).selectinload(MediaStudio.studio),
        )
        stmt = (
            select(SplitCandidate)
            .where(SplitCandidate.status == SplitCandidateStatus.pending)
            .options(selectinload(SplitCandidate.anime).options(media_loader))
            .order_by(SplitCandidate.created_at.asc())
        )
        return list((await db.execute(stmt)).scalars().all())

    async def upsert_pending(
        self,
        db: AsyncSession,
        anime_id: int,
        clusters: list[dict],
        detected_by: str,
    ) -> bool:
        """Insert a pending split_candidate for `anime_id`, OR supersede
        an existing one if its cluster signature has changed.

        Returns True if a row was inserted or superseded; False if a
        prior candidate (pending OR dismissed) with this exact cluster
        signature already exists — admin's previous decision sticks and
        re-detection is a no-op (the common case after a sweep or a
        backfill pass).

        Supersede semantics: dismissing the old pending row and inserting
        a new one preserves admin's prior decisions on other anime (the
        dismissed status survives) while ensuring the live queue always
        reflects the latest detection. Two pending rows for the same
        anime should never coexist — the index `ix_split_candidates_pending`
        scans the pending partition only, but enforcing one-pending-per-
        anime via DAO logic avoids needing a partial-unique-constraint
        migration (PostgreSQL doesn't make those cheap in Alembic).
        """
        new_signature = _cluster_signature(clusters)

        # Sticky dismissal: if admin previously dismissed (or split — for
        # symmetry) a candidate with this exact cluster signature, don't
        # re-flag. Without this guard, dismissing a candidate that the
        # detector still recomputes the same way next sweep would just
        # bounce back as a fresh pending row, defeating the dismissal.
        prior_history = await self._candidates_for_anime(db, anime_id)
        matching_history = next(
            (c for c in prior_history if _cluster_signature(c.clusters) == new_signature),
            None,
        )
        if matching_history is not None:
            if matching_history.status == SplitCandidateStatus.pending:
                # Already pending with matching signature — idempotent no-op.
                return False
            # Dismissed or split with matching signature — admin's call stands.
            return False

        # Different signature than any historical row: this is genuinely new
        # contamination. Supersede the currently-pending row (if any) so
        # the queue surfaces only the latest shape.
        existing_pending = next(
            (c for c in prior_history if c.status == SplitCandidateStatus.pending),
            None,
        )
        if existing_pending is not None:
            existing_pending.status = SplitCandidateStatus.dismissed
            existing_pending.notes = (existing_pending.notes or "") + " [auto-superseded]"
            await db.flush()

        stmt = pg_insert(SplitCandidate).values(
            anime_id=anime_id,
            clusters=clusters,
            detected_by=detected_by,
            status=SplitCandidateStatus.pending,
        )
        await db.execute(stmt)
        return True

    async def _candidates_for_anime(
        self, db: AsyncSession, anime_id: int
    ) -> list[SplitCandidate]:
        """All split_candidate rows for an anime regardless of status.
        Used by upsert_pending to honor sticky dismissals — admin's
        previous "no" on a given cluster signature shouldn't be
        re-flagged by the next detection."""
        stmt = (
            select(SplitCandidate)
            .where(SplitCandidate.anime_id == anime_id)
            .order_by(SplitCandidate.created_at.asc())
        )
        return list((await db.execute(stmt)).scalars().all())
