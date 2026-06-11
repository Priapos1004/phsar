from collections.abc import Collection
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Integer, cast, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.daos.base_dao import BaseDAO
from app.models.anime import Anime
from app.models.anime_search import AnimeSearch
from app.models.media import Media
from app.models.media_relation_edges import MediaRelationEdges
from app.models.media_studio import MediaStudio
from app.models.media_unwanted import MediaUnwanted
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

    async def count_pending(self, db: AsyncSession) -> int:
        """Cheap status='pending' count for the admin bell's pinned
        reminder. The bell polls this on every tick when admin is
        logged in, so it has to stay sub-millisecond — partial index
        keeps the cardinality bounded to currently-pending rows."""
        stmt = (
            select(func.count(MergeCandidate.id))
            .where(MergeCandidate.status == MergeCandidateStatus.pending)
        )
        return (await db.execute(stmt)).scalar_one()

    async def list_pending_with_anime(self, db: AsyncSession) -> list[MergeCandidate]:
        """List pending candidates with both anime + media + studios +
        relation-edge sidecars eagerly loaded. Admin UI shows side-by-side
        summaries AND a reclassification preview per pair, so all of this
        rides one roundtrip."""
        media_loader = selectinload(Anime.media).options(
            selectinload(Media.media_studio).selectinload(MediaStudio.studio),
            selectinload(Media.relation_edges),
        )
        stmt = (
            select(MergeCandidate)
            .where(MergeCandidate.status == MergeCandidateStatus.pending)
            .options(
                selectinload(MergeCandidate.anime_a).options(media_loader),
                selectinload(MergeCandidate.anime_b).options(media_loader),
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

    async def get_cross_anime_relation_pairs(
        self,
        db: AsyncSession,
        *,
        scope_anime_ids: list[int] | None = None,
        allowed_relations: Collection[str],
    ) -> list[tuple[int, int]]:
        """For each `media_relation_edges` row in scope, find target mal_ids
        that resolve to media owned by a different anime via one of
        `allowed_relations`. Returns ordered `(a, b)` pairs with `a < b`,
        deduplicated.

        `scope_anime_ids=None` means catalog-wide; otherwise returns pairs
        where EITHER side is in scope. The caller passes the allowlist so
        the DAO stays decoupled from service policy.

        Implementation: `jsonb_array_elements(edges)` as a LATERAL TVF, then
        JOIN `media` by `(e->>0)::int` to find the target's owning anime.
        OUTER JOIN + IS NULL on `media_unwanted` excludes filtered-franchise
        evidence (Music/PV mal_ids stripped at save time).
        """
        m_src = aliased(Media, name="m_src")
        m_tgt = aliased(Media, name="m_tgt")
        edges_tv = (
            func.jsonb_array_elements(MediaRelationEdges.edges)
            .table_valued("value")
            .lateral("e")
        )
        target_mal_id = cast(edges_tv.c.value.op("->>")(0), Integer)
        relation = edges_tv.c.value.op("->>")(1)
        stmt = (
            select(
                func.least(m_src.anime_id, m_tgt.anime_id).label("a_id"),
                func.greatest(m_src.anime_id, m_tgt.anime_id).label("b_id"),
            )
            .distinct()
            .select_from(m_src)
            .join(MediaRelationEdges, MediaRelationEdges.media_id == m_src.id)
            .join(edges_tv, true())
            .join(m_tgt, m_tgt.mal_id == target_mal_id)
            .outerjoin(MediaUnwanted, MediaUnwanted.mal_id == target_mal_id)
            .where(
                m_src.anime_id != m_tgt.anime_id,
                MediaUnwanted.mal_id.is_(None),
                relation.in_(allowed_relations),
            )
        )
        if scope_anime_ids is not None:
            stmt = stmt.where(
                or_(
                    m_src.anime_id.in_(scope_anime_ids),
                    m_tgt.anime_id.in_(scope_anime_ids),
                )
            )
        result = await db.execute(stmt)
        return [(row.a_id, row.b_id) for row in result.all()]
