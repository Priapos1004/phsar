import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_mal_id_dao import MalIdDAO
from app.daos.rating_dao import rating_of
from app.daos.search_filters import (
    apply_media_filters,
    description_passes,
    fetch_search_results,
    sort_order,
    title_match_passes,
    title_match_score,
    top_percent_ranking,
    upcoming_main_media,
    weighted_score_expr,
)
from app.models.anime import Anime
from app.models.media import Media
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.ratings import Ratings
from app.models.user_settings import NameLanguage
from app.schemas.media_filter_schema import (
    CatalogueSearchFilters,
    SearchType,
    SortDir,
    SortKey,
)
from app.services.vector_embedding_service import generate_query_embedding

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
        """This media's "Top N%" badge (`top_percent_ranking`). None when the media is
        unscored."""
        ranking = top_percent_ranking(per_anime=False)
        return (
            await db.execute(select(ranking.c.top_percent).where(ranking.c.id == media_id))
        ).scalar_one_or_none()

    async def search_media_with_filters(
        self,
        db: AsyncSession,
        query: str,
        filters: CatalogueSearchFilters,
        search_type: SearchType,
        *,
        sort: SortKey,
        sort_dir: SortDir | None,
        name_language: NameLanguage,
        limit: int,
        user_id: int,
        include_ids: set[int] | None,
        exclude_ids: set[int],
    ) -> list[Media]:
        """`include_ids` / `exclude_ids` scope it to the spoiler frontier and the
        caller's personal filters, which the service resolves to media ids."""
        stmt = select(Media)

        if include_ids is not None:
            stmt = stmt.where(Media.id.in_(include_ids))
        if exclude_ids:
            stmt = stmt.where(Media.id.not_in(exclude_ids))

        stmt = apply_media_filters(stmt, filters)
        if filters.upcoming_main:
            stmt = stmt.where(upcoming_main_media())
        your_rating = None
        if sort == SortKey.YOUR_RATING:
            stmt = stmt.outerjoin(Ratings, rating_of(user_id))
            your_rating = Ratings.rating

        stmt = stmt.options(*self._media_eager_options()).limit(limit)

        if query and search_type == SearchType.TITLE:
            title_match = title_match_score(query, Media)
            weighted_score = weighted_score_expr(Media.score, Media.scored_by)
            passes = title_match_passes(
                stmt.order_by(title_match.desc(), weighted_score.desc().nullslast(), Media.id),
                title_match,
            )
        elif query and search_type == SearchType.DESCRIPTION:
            passes = description_passes(stmt, query, await generate_query_embedding(query))
        else:
            passes = [stmt]

        order = None if query and sort == SortKey.RELEVANCE else sort_order(
            sort, sort_dir, name_language, your_rating=your_rating,
        )
        return await fetch_search_results(db, *passes, order=order)
