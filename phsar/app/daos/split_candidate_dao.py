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

    async def get_pending_for_anime(
        self, db: AsyncSession, anime_id: int
    ) -> SplitCandidate | None:
        """At most one pending row per anime by convention (upsert_pending
        supersedes the existing one when the cluster payload changes).
        Used by detection sites to check existence before recomputing."""
        stmt = (
            select(SplitCandidate)
            .where(
                SplitCandidate.anime_id == anime_id,
                SplitCandidate.status == SplitCandidateStatus.pending,
            )
            .order_by(SplitCandidate.created_at.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalars().first()

    async def upsert_pending(
        self,
        db: AsyncSession,
        anime_id: int,
        clusters: list[dict],
        detected_by: str,
    ) -> bool:
        """Insert a pending split_candidate for `anime_id`, OR supersede
        an existing one if its cluster signature has changed.

        Returns True if a row was inserted or superseded; False if an
        existing pending row already matches this cluster payload exactly
        (no-op idempotent re-detection — the common case after a sweep).

        Supersede semantics: dismissing the old row and inserting a new
        one preserves admin's prior decisions on other anime (the
        dismissed status survives) while ensuring the live queue always
        reflects the latest detection. Two pending rows for the same
        anime should never coexist — the index `ix_split_candidates_pending`
        scans the pending partition only, but enforcing one-pending-per-
        anime via DAO logic avoids needing a partial-unique-constraint
        migration (PostgreSQL doesn't make those cheap in Alembic).
        """
        existing = await self.get_pending_for_anime(db, anime_id)
        new_signature = _cluster_signature(clusters)
        if existing is not None:
            if _cluster_signature(existing.clusters) == new_signature:
                return False
            existing.status = SplitCandidateStatus.dismissed
            existing.notes = (existing.notes or "") + " [auto-superseded]"
            await db.flush()

        stmt = pg_insert(SplitCandidate).values(
            anime_id=anime_id,
            clusters=clusters,
            detected_by=detected_by,
            status=SplitCandidateStatus.pending,
        )
        await db.execute(stmt)
        return True
