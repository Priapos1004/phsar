import logging
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_mal_id_dao import MalIdDAO
from app.daos.search_filters import (
    apply_anime_having_filters,
    apply_anime_pre_filters,
    apply_vector_ordering,
)
from app.models.anime import Anime
from app.models.anime_search import AnimeSearch
from app.models.media import Media
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.services.vector_embedding_service import generate_embedding

logger = logging.getLogger(__name__)


class AnimeDAO(MalIdDAO[Anime]):
    def __init__(self):
        super().__init__(Anime)

    @staticmethod
    def _anime_eager_options():
        """Shared eager-load options for anime with media, genres, and studios."""
        return [
            selectinload(Anime.media)
            .selectinload(Media.media_genre)
            .selectinload(MediaGenre.genre),
            selectinload(Anime.media)
            .selectinload(Media.media_studio)
            .selectinload(MediaStudio.studio),
        ]

    async def get_by_uuid_with_all_media(self, db: AsyncSession, uuid: UUID) -> Anime | None:
        """Fetch anime by UUID with all media eagerly loaded (including genres/studios per media)."""
        stmt = (
            select(Anime)
            .filter(Anime.uuid == uuid)
            .options(*self._anime_eager_options())
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def search_anime_aggregated(
        self,
        db: AsyncSession,
        query: str,
        filters: MediaSearchFilters,
        search_type: SearchType,
        limit: int = 50,
    ) -> list[Anime]:
        """Anime search: aggregation query for filtering/ordering,
        then detail fetch for the matched anime.

        Returns Anime objects with eagerly loaded media/genres/studios,
        ordered by search relevance or weighted score."""

        # --- Phase A: Aggregation query (for filtering + ordering only) ---
        avg_score = func.avg(Media.score).label("avg_score")
        avg_scored_by = func.avg(Media.scored_by).label("avg_scored_by")
        total_episodes = func.sum(Media.episodes).label("total_episodes")
        total_watch_time = func.sum(Media.total_watch_time).label("total_watch_time")
        media_count = func.count(Media.id).label("media_count")

        agg_columns = {
            "avg_score": avg_score,
            "avg_scored_by": avg_scored_by,
            "total_episodes": total_episodes,
            "total_watch_time": total_watch_time,
            "media_count": media_count,
        }

        stmt = select(Anime.id)
        stmt = stmt.join(Media, Media.anime_id == Anime.id)

        # Vector search joins
        query_embedding = None
        if query:
            query_embedding = await generate_embedding(query)
            if search_type == SearchType.TITLE:
                stmt = stmt.join(AnimeSearch, AnimeSearch.anime_id == Anime.id)
            elif search_type == SearchType.DESCRIPTION:
                # LEFT JOIN so anime with some media missing embeddings still appear;
                # avg() naturally ignores NULLs from the outer join
                stmt = stmt.outerjoin(MediaSearch, MediaSearch.media_id == Media.id)

        # Pre-aggregation WHERE filters (any-match semantics)
        stmt = apply_anime_pre_filters(stmt, filters)

        # GROUP BY — include AnimeSearch.title_embedding for title search
        # since it's one-to-one with Anime and used in ORDER BY
        group_cols = [Anime.id]
        if query and search_type == SearchType.TITLE:
            group_cols.append(AnimeSearch.title_embedding)
        stmt = stmt.group_by(*group_cols)

        # Post-aggregation HAVING filters (majority/range semantics)
        stmt = apply_anime_having_filters(stmt, filters, agg_columns)

        # Ordering
        if query and query_embedding is not None:
            if search_type == SearchType.TITLE:
                stmt = apply_vector_ordering(
                    stmt, search_type, query_embedding,
                    extra_columns={SearchType.TITLE: AnimeSearch.title_embedding},
                )
            elif search_type == SearchType.DESCRIPTION:
                avg_distance = func.avg(
                    func.cosine_distance(MediaSearch.description_embedding, cast(query_embedding, Vector))
                ).label("avg_distance")
                stmt = stmt.add_columns(avg_distance)
                stmt = stmt.order_by(avg_distance)
        else:
            # Default ordering: weighted score = avg(score) * log10(avg(scored_by) + 1)
            # log10 chosen over ln to dampen the scored_by weight — prevents very popular
            # but mediocre-scored anime from outranking higher-scored niche anime
            weighted = avg_score * func.log(avg_scored_by + 1)
            stmt = stmt.order_by(weighted.desc().nullslast())

        stmt = stmt.limit(limit)

        result = await db.execute(stmt)
        agg_rows = result.all()

        if not agg_rows:
            return []

        # --- Phase B: Detail fetch for matched anime ---
        anime_ids = [row[0] for row in agg_rows]
        detail_stmt = (
            select(Anime)
            .where(Anime.id.in_(anime_ids))
            .options(*self._anime_eager_options())
        )
        detail_result = await db.execute(detail_stmt)
        anime_map = {a.id: a for a in detail_result.scalars().all()}

        # Preserve aggregation query ordering
        return [anime_map[aid] for aid in anime_ids if aid in anime_map]
