import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.genre_dao import GenreDAO
from app.daos.media_dao import MediaDAO
from app.daos.studio_dao import StudioDAO

logger = logging.getLogger(__name__)

media_dao = MediaDAO()
genre_dao = GenreDAO()
studio_dao = StudioDAO()

def sort_seasons(seasons: list[str]) -> list[str]:
    season_order = {'Winter': 1, 'Spring': 2, 'Summer': 3, 'Fall': 4}
    
    def season_sort_key(item):
        parts = item.split()
        if len(parts) == 2:
            season, year = parts
            return (int(year), season_order.get(season, 99))
        return (9999, 99)  # Put unparseable items at the end

    return sorted(seasons, key=season_sort_key, reverse=True)

def sort_age_ratings(age_rating_tuples: list[tuple[str, int]]) -> list[str]:
    """Sort by numeric value first, then return string value."""
    sorted_pairs = sorted(
        age_rating_tuples,
        key=lambda t: (t[1] is None, t[1])  # None sorts last
    )
    return [s for s, _ in sorted_pairs if s is not None]

async def fetch_filter_values(db: AsyncSession) -> dict:
    relation_types = await media_dao.get_unique_in_field(db, field_name="relation_type")
    media_types = await media_dao.get_unique_in_field(db, field_name="media_type")

    age_rating_tuples = await media_dao.get_unique_in_fields(db, field_names=["age_rating", "age_rating_numeric"])
    age_rating_values = sort_age_ratings(age_rating_tuples)

    airing_status = await media_dao.get_unique_in_field(db, field_name="airing_status")

    anime_seasons_tuple = await media_dao.get_unique_in_fields(db, field_names=["anime_season_name", "anime_season_year"])
    anime_seasons = sort_seasons([f"{name.value} {year}" for name, year in anime_seasons_tuple if name and year])

    genre_names = await genre_dao.get_distinct_used_genres(db)
    studio_names = await studio_dao.get_distinct_used_studios(db)

    score_min, score_max = 0.0, 10.0 # Set score range to full possible range
    scored_by_min, scored_by_max = 0, (await media_dao.get_min_max(db, "scored_by"))[1]
    episodes_min, episodes_max = await media_dao.get_min_max(db, "episodes")
    duration_min, duration_max = await media_dao.get_min_max(db, "duration_seconds")
    watch_time_min, watch_time_max = await media_dao.get_min_max(db, "total_watch_time")

    filter_values = {
        "relation_type": relation_types,
        "media_type": media_types,
        "age_rating": age_rating_values,
        "airing_status": airing_status,
        "anime_season": anime_seasons,
        "genre_name": genre_names,
        "studio_name": studio_names,
        "score_min": score_min,
        "score_max": score_max,
        "scored_by_min": scored_by_min,
        "scored_by_max": scored_by_max,
        "episodes_min": episodes_min,
        "episodes_max": episodes_max,
        "duration_per_episode_min": duration_min,
        "duration_per_episode_max": duration_max,
        "total_watch_time_min": watch_time_min,
        "total_watch_time_max": watch_time_max,
    }
    logger.debug("Filter values:\n%s", filter_values)
    return filter_values
