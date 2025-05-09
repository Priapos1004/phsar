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
        return (9999, 99)  # put unparseable items at the end

    return sorted(seasons, key=season_sort_key)

async def fetch_filter_values(db: AsyncSession) -> dict:
    relation_types = await media_dao.get_unique_in_field(db, field_name="relation_type")
    media_types = await media_dao.get_unique_in_field(db, field_name="media_type")
    fsk_values = await media_dao.get_unique_in_field(db, field_name="fsk")
    airing_status = await media_dao.get_unique_in_field(db, field_name="airing_status")
    
    anime_seasons = await media_dao.get_unique_in_field(db, field_name="anime_season")
    anime_seasons = sort_seasons(anime_seasons)

    genre_names = await genre_dao.get_distinct_used_genres(db)
    studio_names = await studio_dao.get_distinct_used_studios(db)

    score_min, score_max = await media_dao.get_min_max(db, "score")
    scored_by_min, scored_by_max = await media_dao.get_min_max(db, "scored_by")
    episodes_min, episodes_max = await media_dao.get_min_max(db, "episodes")
    duration_min, duration_max = await media_dao.get_min_max(db, "duration_seconds")
    watch_time_min, watch_time_max = await media_dao.get_min_max(db, "total_watch_time")

    return {
        "relation_type": relation_types,
        "media_type": media_types,
        "fsk": fsk_values,
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
