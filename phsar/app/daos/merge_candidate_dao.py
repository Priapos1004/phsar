from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.anime import Anime
from app.models.anime_search import AnimeSearch
from app.models.media import Media
from app.models.media_studio import MediaStudio
from app.models.merge_candidate import MergeCandidate, MergeCandidateStatus
from app.models.ratings import Ratings

if TYPE_CHECKING:
    from app.services.merge_detection_service import AnimeForDetection


class MergeCandidateDAO(BaseDAO[MergeCandidate]):
    def __init__(self):
        super().__init__(MergeCandidate)

    async def get_by_uuid(self, db: AsyncSession, uuid: UUID) -> MergeCandidate | None:
        stmt = select(MergeCandidate).where(MergeCandidate.uuid == uuid)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def list_pending_with_anime(self, db: AsyncSession) -> list[MergeCandidate]:
        """List pending candidates with both anime + media + studios eagerly loaded.

        Admin UI shows side-by-side titles/years/studios per pair, so loading
        media and studios here keeps the response a single roundtrip."""
        media_studio_loader = (
            selectinload(Anime.media)
            .selectinload(Media.media_studio)
            .selectinload(MediaStudio.studio)
        )
        stmt = (
            select(MergeCandidate)
            .where(MergeCandidate.status == MergeCandidateStatus.pending)
            .options(
                selectinload(MergeCandidate.anime_a).options(media_studio_loader),
                selectinload(MergeCandidate.anime_b).options(media_studio_loader),
            )
            .order_by(MergeCandidate.created_at.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def upsert_pending(
        self,
        db: AsyncSession,
        anime_a_id: int,
        anime_b_id: int,
        similarity_score: float,
        detected_by: str,
    ) -> None:
        """Insert a pending candidate, ignore if a row for this pair already exists.

        Caller must have ordered ids ascending (anime_a_id < anime_b_id) so the
        unique constraint and CHECK constraint are satisfied. Uses
        ON CONFLICT DO NOTHING so re-detecting the same pair across multiple
        scrapes is a no-op rather than an error."""
        if anime_a_id >= anime_b_id:
            raise ValueError(
                f"anime_a_id must be < anime_b_id, got {anime_a_id} and {anime_b_id}"
            )
        stmt = (
            pg_insert(MergeCandidate)
            .values(
                anime_a_id=anime_a_id,
                anime_b_id=anime_b_id,
                similarity_score=similarity_score,
                detected_by=detected_by,
                status=MergeCandidateStatus.pending,
            )
            .on_conflict_do_nothing(constraint="uq_merge_candidates_pair")
        )
        await db.execute(stmt)

    async def get_rating_counts_for_anime(
        self, db: AsyncSession, anime_ids: set[int]
    ) -> dict[int, int]:
        """Total ratings across each anime's media. Used by the admin merge
        UI to tiebreak A/B ordering on "which side has more user data".
        Anime with zero ratings are absent — caller defaults to 0."""
        if not anime_ids:
            return {}
        stmt = (
            select(Media.anime_id, func.count(Ratings.id))
            .join(Ratings, Ratings.media_id == Media.id)
            .where(Media.anime_id.in_(anime_ids))
            .group_by(Media.anime_id)
        )
        result = await db.execute(stmt)
        return {anime_id: count for anime_id, count in result.all()}

    async def get_existing_pairs(self, db: AsyncSession) -> set[tuple[int, int]]:
        """Returns every (a_id, b_id) pair that already has a row, regardless
        of status. Detection skips these pairs to avoid the SequenceMatcher
        cost — the unique constraint would catch them anyway, but pre-filtering
        keeps the inner loop O(catalog²) flat as the table grows over time."""
        stmt = select(MergeCandidate.anime_a_id, MergeCandidate.anime_b_id)
        result = await db.execute(stmt)
        return {(a, b) for a, b in result.all()}

    async def get_anime_for_detection(
        self, db: AsyncSession
    ) -> list["AnimeForDetection"]:
        """One AnimeForDetection per anime that has at least one studio linked
        through its media. Description embedding may be None if the AnimeSearch
        row hasn't been backfilled yet — the detector treats that as "skip the
        desc signal". Anime with zero studios drop out of the join — the
        detector ignores them either way."""
        # Imported here to avoid a circular import: merge_detection_service
        # imports the DAO at module load.
        from app.services.merge_detection_service import AnimeForDetection

        stmt = (
            select(
                Anime.id,
                Anime.title,
                MediaStudio.studio_id,
                AnimeSearch.description_embedding,
            )
            .join(Media, Media.anime_id == Anime.id)
            .join(MediaStudio, MediaStudio.media_id == Media.id)
            .outerjoin(AnimeSearch, AnimeSearch.anime_id == Anime.id)
        )
        result = await db.execute(stmt)

        per_anime: dict[int, dict] = {}
        for anime_id, title, studio_id, desc_emb in result.all():
            entry = per_anime.setdefault(
                anime_id,
                {"title": title, "studios": set(), "desc": desc_emb},
            )
            entry["studios"].add(studio_id)
        return [
            AnimeForDetection(
                id=aid,
                title=e["title"],
                studios=e["studios"],
                description_embedding=e["desc"],
            )
            for aid, e in per_anime.items()
        ]
