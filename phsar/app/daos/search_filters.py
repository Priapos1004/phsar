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


def _apply_studio_filter(stmt, studio_names: list[str]):
    """Subquery-based studio filter to avoid duplicate rows from multiple matching studios."""
    studio_subquery = (
        select(MediaStudio.media_id)
        .join(MediaStudio.studio)
        .where(Studio.name.in_(studio_names))
    ).subquery()
    return stmt.where(Media.id.in_(select(studio_subquery.c.media_id)))


def _parse_season_filters(anime_season: list[str]) -> list[tuple]:
    """Parse 'Season Year' strings into (year, SeasonType) tuples."""
    filter_pairs = []
    for part in anime_season:
        try:
            season, year = part.split(" ", 1)
            filter_pairs.append((int(year), SeasonType[season]))
        except (ValueError, KeyError):
            logger.warning("Ignoring malformed anime_season filter: %s", part)
    return filter_pairs


def _build_categorical_conditions(filters: MediaSearchFilters) -> list:
    """Build WHERE conditions for categorical media filters (media_type, relation_type, etc.)."""
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
        filter_pairs = _parse_season_filters(filters.anime_season)
        if filter_pairs:
            conditions.append(
                tuple_(Media.anime_season_year, Media.anime_season_name).in_(filter_pairs)
            )
    return conditions


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

    if filters.studio_name:
        stmt = _apply_studio_filter(stmt, filters.studio_name)

    conditions = _build_categorical_conditions(filters)

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


def apply_anime_pre_filters(stmt, filters: MediaSearchFilters):
    """Apply WHERE-clause filters with 'any' semantics for anime-level search.
    These narrow which media rows enter the GROUP BY. Genre and range filters
    are excluded — they use HAVING on aggregated values instead."""

    if filters.studio_name:
        stmt = _apply_studio_filter(stmt, filters.studio_name)

    conditions = _build_categorical_conditions(filters)

    if conditions:
        stmt = stmt.where(and_(*conditions))

    return stmt


def apply_anime_having_filters(stmt, filters: MediaSearchFilters, agg_columns: dict):
    """Apply HAVING-clause filters on aggregated values for anime-level search.
    agg_columns maps field names to SQLAlchemy aggregate column expressions."""
    # Deferred import to avoid circular dependency: search_filters <- anime_dao <- search_filters
    from app.models.anime import Anime

    conditions = []

    if filters.score_min is not None:
        conditions.append(agg_columns["avg_score"].isnot(None) & (agg_columns["avg_score"] >= filters.score_min))
    if filters.score_max is not None:
        conditions.append(agg_columns["avg_score"].isnot(None) & (agg_columns["avg_score"] <= filters.score_max))
    if filters.scored_by_min is not None:
        conditions.append(agg_columns["avg_scored_by"] >= filters.scored_by_min)
    if filters.scored_by_max is not None:
        conditions.append(agg_columns["avg_scored_by"] <= filters.scored_by_max)
    if filters.episodes_min is not None:
        conditions.append(agg_columns["total_episodes"].isnot(None) & (agg_columns["total_episodes"] >= filters.episodes_min))
    if filters.episodes_max is not None:
        conditions.append(agg_columns["total_episodes"].isnot(None) & (agg_columns["total_episodes"] <= filters.episodes_max))
    if filters.total_watch_time_min is not None:
        conditions.append(agg_columns["total_watch_time"].isnot(None) & (agg_columns["total_watch_time"] >= filters.total_watch_time_min))
    if filters.total_watch_time_max is not None:
        conditions.append(agg_columns["total_watch_time"].isnot(None) & (agg_columns["total_watch_time"] <= filters.total_watch_time_max))

    # Genre majority filter: for each selected genre, a correlated subquery checks
    # if >50% of the anime's media have that genre. This mirrors the threshold in
    # filter_service._get_anime_majority_genres, which uses the same formula to
    # determine which genres appear in the dropdown.
    if filters.genre_name:
        for genre_name in filters.genre_name:
            genre_count_subq = (
                select(func.count(Media.id))
                .join(Media.media_genre)
                .join(MediaGenre.genre)
                .where(Media.anime_id == Anime.id)
                .where(Genre.name == genre_name)
                .correlate(Anime)
                .scalar_subquery()
            )
            conditions.append(genre_count_subq * 2 > agg_columns["media_count"])

    if conditions:
        stmt = stmt.having(and_(*conditions))

    return stmt


def apply_vector_ordering(stmt, search_type: SearchType, query_embedding, extra_columns: dict | None = None):
    """Apply cosine distance ordering for vector similarity search.
    extra_columns allows callers to register additional search type → embedding column mappings
    (e.g., RATING_NOTES → RatingSearch.note_embedding)."""
    columns = {**_VECTOR_COLUMNS, **(extra_columns or {})}
    column = columns.get(search_type)
    if column is not None:
        stmt = stmt.order_by(func.cosine_distance(column, cast(query_embedding, Vector)))
    else:
        logger.warning("No embedding column for search_type=%s; results will not be relevance-ordered", search_type)
    return stmt
