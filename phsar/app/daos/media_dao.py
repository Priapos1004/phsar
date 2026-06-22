import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_mal_id_dao import MalIdDAO
from app.daos.search_filters import (
    apply_media_filters,
    apply_vector_ordering,
    weighted_score_expr,
)
from app.models.anime import Anime
from app.models.media import Media
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.services.vector_embedding_service import generate_embedding

logger = logging.getLogger(__name__)


class MediaDAO(MalIdDAO[Media]):
    def __init__(self):
        super().__init__(Media)

    def _media_eager_options(self):
        """Shared eager-load options for genres, studios, and anime."""
        return [
            selectinload(Media.media_genre).selectinload(MediaGenre.genre),
            selectinload(Media.media_studio).selectinload(MediaStudio.studio),
            selectinload(Media.anime),
        ]

    async def get_by_uuid_with_relations(self, db: AsyncSession, uuid: UUID) -> Media | None:
        """Fetch a single media by UUID with genres, studios, and anime eagerly loaded.
        Also loads the anime's media list for sibling navigation."""
        stmt = (
            select(Media)
            .filter(Media.uuid == uuid)
            .options(
                *self._media_eager_options(),
                # Load sibling media through the anime relationship for the detail page carousel
                selectinload(Media.anime).selectinload(Anime.media),
            )
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def score_top_percent(self, db: AsyncSession, media_id: int) -> int | None:
        """Where this media ranks among all scored media by its
        confidence-weighted MAL score, as a "top N%" (1 = best).

        Metric is `score * log10(scored_by + 1)` — the same weighting search
        ranking uses — so a high score from a handful of votes doesn't outrank
        a well-voted title. Returns None when the media is unscored or the
        catalog has no scored media.

        Single seq scan over the scored rows, no sort: `better` counts those
        beating this media's metric, `total` counts all scored. (A `rank()`
        window form would force a sort the count-FILTER avoids, and an index on
        the metric can't help a rank-against-all-rows anyway — EXPLAIN confirmed
        the planner sorts regardless. If this ever matters at 10k+ media, cache
        the percentile at sweep time rather than reshaping the query.)"""
        metric = weighted_score_expr(Media.score, Media.scored_by)
        this_metric = (
            select(metric).where(Media.id == media_id).scalar_subquery()
        )
        stmt = select(
            this_metric.label("m_this"),
            func.count().filter(metric > this_metric),
            func.count(),
        ).where(Media.score.is_not(None))
        m_this, better, total = (await db.execute(stmt)).one()
        if m_this is None or total == 0:
            return None
        return max(1, round(better / total * 100))

    async def search_media_by_vector_with_filters(
        self,
        db: AsyncSession,
        query: str,
        filters: MediaSearchFilters,
        search_type: SearchType,
        limit: int = 50,
        visible_media_ids: set[int] | None = None,
    ) -> list[Media]:
        stmt = select(Media)

        if query != "":
            query_embedding = await generate_embedding(query)
            # Inner join ensures only media with embeddings are searched
            stmt = stmt.join(MediaSearch)

        if visible_media_ids is not None:
            stmt = stmt.where(Media.id.in_(visible_media_ids))

        stmt = apply_media_filters(stmt, filters)

        stmt = stmt.options(*self._media_eager_options())

        if query != "":
            stmt = apply_vector_ordering(
                stmt, search_type, query_embedding,
                query=query,
                title_columns=[Media.title, Media.name_eng],
            )
        else:
            weighted_score = weighted_score_expr(Media.score, Media.scored_by)
            stmt = stmt.order_by(weighted_score.desc().nullslast())

        stmt = stmt.limit(limit)

        results = (await db.execute(stmt)).scalars().all()
        return results
