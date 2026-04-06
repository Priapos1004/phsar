import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_mal_id_dao import MalIdDAO
from app.daos.search_filters import apply_media_filters, apply_vector_ordering
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

    async def search_media_by_vector_with_filters(
        self,
        db: AsyncSession,
        query: str,
        filters: MediaSearchFilters,
        search_type: SearchType,
        limit: int = 50,
    ) -> list[Media]:
        stmt = select(Media)

        if query != "":
            query_embedding = await generate_embedding(query)
            # Inner join ensures only media with embeddings are searched
            stmt = stmt.join(MediaSearch)

        stmt = apply_media_filters(stmt, filters)

        stmt = stmt.options(*self._media_eager_options())

        if query != "":
            stmt = apply_vector_ordering(stmt, search_type, query_embedding)
        else:
            # log10 chosen over ln to dampen the scored_by weight — prevents very popular
            # but mediocre-scored media from outranking higher-scored niche media
            weighted_score = Media.score * func.log(Media.scored_by + 1)
            stmt = stmt.order_by(weighted_score.desc().nullslast())

        stmt = stmt.limit(limit)

        results = (await db.execute(stmt)).scalars().all()
        return results
