import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_dao import MediaDAO
from app.exceptions import MediaNotFoundError
from app.models.media import Media
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.schemas.media_schema import MediaConnected, MediaDetail, MediaSibling

logger = logging.getLogger(__name__)

media_dao = MediaDAO()


def media_to_dict(media: Media) -> dict:
    """Extract media fields into a dict for Pydantic schema construction.
    Flattens ORM relationships (genres, studios, anime) into plain values."""
    return {
        "mal_id": media.mal_id,
        "mal_url": media.mal_url,
        "title": media.title,
        "name_eng": media.name_eng,
        "name_jap": media.name_jap,
        "other_names": media.other_names,
        "media_type": media.media_type,
        "relation_type": media.relation_type,
        "age_rating": media.age_rating,
        "description": media.description,
        "original_source": media.original_source,
        "cover_image": media.cover_image,
        "score": media.score,
        "scored_by": media.scored_by,
        "episodes": media.episodes,
        "anime_season_name": media.anime_season_name,
        "anime_season_year": media.anime_season_year,
        "airing_status": media.airing_status,
        "aired_from": media.aired_from,
        "aired_to": media.aired_to,
        "duration": media.duration,
        "duration_seconds": media.duration_seconds,
        "genres": [g.genre.name for g in media.media_genre],
        "studio": [s.studio.name for s in media.media_studio],
        "anime_uuid": media.anime.uuid,
        "anime_title": media.anime.title,
        "anime_name_eng": media.anime.name_eng,
        "anime_name_jap": media.anime.name_jap,
        "anime_other_names": media.anime.other_names,
        "uuid": media.uuid,
        "total_watch_time": media.total_watch_time,
        "age_rating_numeric": media.age_rating_numeric,
    }


def map_media_to_connected(media: Media) -> MediaConnected:
    return MediaConnected(**media_to_dict(media))


async def search_media_by_query(
    db: AsyncSession,
    query: str,
    filters: MediaSearchFilters,
    search_type: SearchType,
    visible_media_ids: set[int] | None = None,
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
        visible_media_ids=visible_media_ids,
    )

    # Map to MediaConnected Pydantic models
    return [map_media_to_connected(m) for m in media_list]


def _media_to_sibling(media: Media) -> MediaSibling:
    return MediaSibling(
        uuid=media.uuid,
        title=media.title,
        name_eng=media.name_eng,
        name_jap=media.name_jap,
        cover_image=media.cover_image,
        media_type=media.media_type,
        relation_type=media.relation_type,
        episodes=media.episodes,
        airing_status=media.airing_status,
        anime_season_name=media.anime_season_name,
        anime_season_year=media.anime_season_year,
    )


async def get_media_detail(db: AsyncSession, media_uuid: UUID) -> MediaDetail:
    media = await media_dao.get_by_uuid_with_relations(db, media_uuid)
    if not media:
        raise MediaNotFoundError(str(media_uuid))

    siblings = [
        _media_to_sibling(m) for m in media.anime.media if m.id != media.id
    ]

    return MediaDetail(**media_to_dict(media), sibling_media=siblings)
