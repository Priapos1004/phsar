import logging

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, cast, distinct, func, select, tuple_

from app.models.genre import Genre
from app.models.media import Media, SeasonType
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType

logger = logging.getLogger(__name__)

# Base mapping from search type to the embedding column used for cosine distance ordering
_VECTOR_COLUMNS = {
    SearchType.TITLE: MediaSearch.title_embedding,
    SearchType.DESCRIPTION: MediaSearch.description_embedding,
}


def apply_media_filters(stmt, filters: MediaSearchFilters):
    """Apply media metadata filters (genre, studio, scores, etc.) to a query.
    The statement must already have Media accessible (via select or join)."""

    # Genre filter: require media to have ALL specified genres
    if filters.genre_name:
        unique_genres = set(filters.genre_name)
        subquery = (
            select(Media.id)
            .join(Media.media_genre)
            .join(MediaGenre.genre)
            .where(Genre.name.in_(unique_genres))
            .group_by(Media.id)
            .having(func.count(distinct(Genre.id)) >= len(unique_genres))
        ).subquery()
        stmt = stmt.where(Media.id.in_(select(subquery.c.id)))

    # Studio filter
    if filters.studio_name:
        stmt = (
            stmt
            .join(Media.media_studio)
            .join(MediaStudio.studio)
            .where(Studio.name.in_(filters.studio_name))
        )

    # Scalar conditions on media columns
    conditions = []

    if filters.media_type:
        conditions.append(Media.media_type.in_(filters.media_type))
    if filters.relation_type:
        conditions.append(Media.relation_type.in_(filters.relation_type))
    if filters.age_rating:
        conditions.append(Media.age_rating.in_(filters.age_rating))
    if filters.airing_status:
        conditions.append(Media.airing_status.in_(filters.airing_status))
    if filters.anime_season:
        filter_pairs = []
        for part in filters.anime_season:
            try:
                season, year = part.split(" ", 1)
                filter_pairs.append((int(year), SeasonType[season]))
            except (ValueError, KeyError):
                logger.warning("Ignoring malformed anime_season filter: %s", part)
        if filter_pairs:
            conditions.append(
                tuple_(Media.anime_season_year, Media.anime_season_name).in_(filter_pairs)
            )
    if filters.score_min is not None:
        conditions.append(Media.score.isnot(None) & (Media.score >= filters.score_min))
    if filters.score_max is not None:
        conditions.append(Media.score.isnot(None) & (Media.score <= filters.score_max))
    if filters.scored_by_min is not None:
        conditions.append(Media.scored_by >= filters.scored_by_min)
    if filters.scored_by_max is not None:
        conditions.append(Media.scored_by <= filters.scored_by_max)
    if filters.episodes_min is not None:
        conditions.append(Media.episodes.isnot(None) & (Media.episodes >= filters.episodes_min))
    if filters.episodes_max is not None:
        conditions.append(Media.episodes.isnot(None) & (Media.episodes <= filters.episodes_max))
    if filters.duration_per_episode_min is not None:
        conditions.append(
            Media.duration_seconds.isnot(None) & (Media.duration_seconds >= filters.duration_per_episode_min)
        )
    if filters.duration_per_episode_max is not None:
        conditions.append(
            Media.duration_seconds.isnot(None) & (Media.duration_seconds <= filters.duration_per_episode_max)
        )
    if filters.total_watch_time_min is not None:
        conditions.append(
            Media.total_watch_time.isnot(None) & (Media.total_watch_time >= filters.total_watch_time_min)
        )
    if filters.total_watch_time_max is not None:
        conditions.append(
            Media.total_watch_time.isnot(None) & (Media.total_watch_time <= filters.total_watch_time_max)
        )

    if conditions:
        stmt = stmt.where(and_(*conditions))

    return stmt


def apply_vector_ordering(stmt, search_type: SearchType, query_embedding, extra_columns: dict | None = None):
    """Apply cosine distance ordering for vector similarity search.
    extra_columns allows callers to register additional search type → embedding column mappings
    (e.g., RATING_NOTES → RatingSearch.note_embedding)."""
    columns = {**_VECTOR_COLUMNS, **(extra_columns or {})}
    column = columns.get(search_type)
    if column is not None:
        stmt = stmt.order_by(func.cosine_distance(column, cast(query_embedding, Vector)))
    return stmt
