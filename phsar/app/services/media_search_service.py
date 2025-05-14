import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_dao import MediaDAO
from app.models.media import Media
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.schemas.media_schema import MediaConnected

logger = logging.getLogger(__name__)

media_dao = MediaDAO()


def _map_to_connected(media: Media) -> MediaConnected:
    return MediaConnected(
        mal_id=media.mal_id,
        mal_url=media.mal_url,
        title=media.title,
        name_eng=media.name_eng,
        name_jap=media.name_jap,
        other_names=media.other_names,
        media_type=media.media_type,
        relation_type=media.relation_type,
        fsk=media.fsk,
        description=media.description,
        original_source=media.original_source,
        cover_image=media.cover_image,
        score=media.score,
        scored_by=media.scored_by,
        episodes=media.episodes,
        anime_season=media.anime_season,
        airing_status=media.airing_status,
        aired_from=media.aired_from,
        aired_to=media.aired_to,
        duration=media.duration,
        duration_seconds=media.duration_seconds,
        genres=[g.genre.name for g in media.media_genre],
        studio=[s.studio.name for s in media.media_studio],
        anime_uuid=media.anime.uuid,
        anime_title=media.anime.title,
        anime_name_eng=media.anime.name_eng,
        anime_name_jap=media.anime.name_jap,
        anime_other_names=media.anime.other_names,
        uuid=media.uuid,
    )


async def search_media_by_query(
    db: AsyncSession,
    query: str,
    filters: MediaSearchFilters,
    search_type: SearchType,
) -> list[MediaConnected]:
    logger.info(f"Query: {query}")
    logger.info(f"Filters: {filters.model_dump()}")
    logger.info(f"Search type: {search_type}")
    # Get ORM objects from DAO
    media_list: list[Media] = await media_dao.search_media_by_vector_with_filters(
        db=db,
        query=query,
        filters=filters,
        search_type=search_type,
    )

    # Map to MediaConnected Pydantic models
    return [_map_to_connected(m) for m in media_list]
