import logging

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.genre_dao import GenreDAO
from app.daos.media_dao import MediaDAO
from app.daos.studio_dao import StudioDAO
from app.models.genre import Genre
from app.models.media import Media
from app.models.media_genre import MediaGenre
from app.schemas.media_filter_schema import ViewType

logger = logging.getLogger(__name__)

media_dao = MediaDAO()
genre_dao = GenreDAO()
studio_dao = StudioDAO()

SEASON_ORDER = {"Winter": 1, "Spring": 2, "Summer": 3, "Fall": 4}

def sort_seasons(seasons: list[str]) -> list[str]:
    def season_sort_key(item):
        parts = item.split()
        if len(parts) == 2:
            season, year = parts
            return (int(year), SEASON_ORDER.get(season, 99))
        return (9999, 99)  # Put unparseable items at the end

    return sorted(seasons, key=season_sort_key, reverse=True)

def sort_age_ratings(age_rating_tuples: list[tuple[str, int]]) -> list[str]:
    """Sort by numeric value first, then return string value."""
    sorted_pairs = sorted(
        age_rating_tuples,
        key=lambda t: (t[1] is None, t[1])  # None sorts last
    )
    return [s for s, _ in sorted_pairs if s is not None]


async def _get_anime_majority_genres(db: AsyncSession) -> list[str]:
    """Get genres that pass majority rule (>50% of media) for at least one anime.
    Populates the genre dropdown; the same threshold is applied per-anime in
    search_filters.apply_anime_having_filters when filtering search results."""
    # For each (anime_id, genre), count media with that genre and total media.
    # Keep genres where count * 2 > total for at least one anime.
    media_count_subq = (
        select(Media.anime_id, func.count(Media.id).label("total"))
        .group_by(Media.anime_id)
    ).subquery()

    genre_count_subq = (
        select(
            Media.anime_id,
            Genre.name.label("genre_name"),
            func.count(Media.id).label("genre_count"),
        )
        .join(MediaGenre, MediaGenre.media_id == Media.id)
        .join(Genre, Genre.id == MediaGenre.genre_id)
        .group_by(Media.anime_id, Genre.name)
    ).subquery()

    stmt = (
        select(distinct(genre_count_subq.c.genre_name))
        .join(
            media_count_subq,
            media_count_subq.c.anime_id == genre_count_subq.c.anime_id,
        )
        .where(genre_count_subq.c.genre_count * 2 > media_count_subq.c.total)
        .order_by(genre_count_subq.c.genre_name)
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


async def _get_anime_aggregated_ranges(db: AsyncSession) -> dict:
    """Get min/max of aggregated values across all anime for filter slider ranges."""
    # Subquery: per-anime aggregates (avg scored_by to avoid bias toward anime with more entries)
    anime_agg = (
        select(
            Media.anime_id,
            func.sum(Media.episodes).label("total_episodes"),
            func.sum(Media.total_watch_time).label("total_watch_time"),
            func.avg(Media.scored_by).label("avg_scored_by"),
        )
        .group_by(Media.anime_id)
    ).subquery()

    stmt = select(
        func.min(anime_agg.c.total_episodes),
        func.max(anime_agg.c.total_episodes),
        func.min(anime_agg.c.total_watch_time),
        func.max(anime_agg.c.total_watch_time),
        func.max(anime_agg.c.avg_scored_by),
    )
    result = await db.execute(stmt)
    row = result.one()

    return {
        "episodes_min": row[0],
        "episodes_max": row[1],
        "total_watch_time_min": row[2],
        "total_watch_time_max": row[3],
        "scored_by_min": 0,
        "scored_by_max": int(row[4]) if row[4] is not None else None,
    }


async def _fetch_shared_filter_values(db: AsyncSession) -> dict:
    """Categorical filter values shared between media and anime views."""
    relation_types = await media_dao.get_unique_in_field(db, field_name="relation_type")
    media_types = await media_dao.get_unique_in_field(db, field_name="media_type")

    age_rating_tuples = await media_dao.get_unique_in_fields(db, field_names=["age_rating", "age_rating_numeric"])
    age_rating_values = sort_age_ratings(age_rating_tuples)

    airing_status = await media_dao.get_unique_in_field(db, field_name="airing_status")

    anime_seasons_tuple = await media_dao.get_unique_in_fields(db, field_names=["anime_season_name", "anime_season_year"])
    anime_seasons = sort_seasons([f"{name.value} {year}" for name, year in anime_seasons_tuple if name and year])

    studio_names = await studio_dao.get_distinct_used_studios(db)

    return {
        "relation_type": relation_types,
        "media_type": media_types,
        "age_rating": age_rating_values,
        "airing_status": airing_status,
        "anime_season": anime_seasons,
        "studio_name": studio_names,
        "score_min": 0.0,
        "score_max": 10.0,
    }


async def fetch_filter_values(db: AsyncSession, view_type: ViewType = ViewType.MEDIA) -> dict:
    shared = await _fetch_shared_filter_values(db)

    if view_type == ViewType.ANIME:
        genre_names = await _get_anime_majority_genres(db)
        anime_ranges = await _get_anime_aggregated_ranges(db)
        filter_values = {
            **shared,
            "genre_name": genre_names,
            **anime_ranges,
            # Anime view has no per-episode duration filter
            "duration_per_episode_min": None,
            "duration_per_episode_max": None,
        }
    else:
        genre_names = await genre_dao.get_distinct_used_genres(db)
        scored_by_min, scored_by_max = 0, (await media_dao.get_min_max(db, "scored_by"))[1]
        episodes_min, episodes_max = await media_dao.get_min_max(db, "episodes")
        duration_min, duration_max = await media_dao.get_min_max(db, "duration_seconds")
        watch_time_min, watch_time_max = await media_dao.get_min_max(db, "total_watch_time")

        filter_values = {
            **shared,
            "genre_name": genre_names,
            "scored_by_min": scored_by_min,
            "scored_by_max": scored_by_max,
            "episodes_min": episodes_min,
            "episodes_max": episodes_max,
            "duration_per_episode_min": duration_min,
            "duration_per_episode_max": duration_max,
            "total_watch_time_min": watch_time_min,
            "total_watch_time_max": watch_time_max,
        }

    logger.debug("Filter values (view_type=%s):\n%s", view_type, filter_values)
    return filter_values
