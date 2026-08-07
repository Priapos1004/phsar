import logging

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.genre_dao import GenreDAO
from app.daos.media_dao import MediaDAO
from app.daos.search_filters import (
    anime_genre_majority_relation,
    weighted_mean_votes_expr,
)
from app.daos.studio_dao import StudioDAO
from app.models.media import Media
from app.schemas.genre_schema import GenreOut
from app.schemas.media_filter_schema import ViewType

logger = logging.getLogger(__name__)

media_dao = MediaDAO()
genre_dao = GenreDAO()
studio_dao = StudioDAO()

SEASON_ORDER = {"Winter": 1, "Spring": 2, "Summer": 3, "Fall": 4}


def chronological_media_key(
    season_year: int | None,
    season_name: str | None,
    mal_id: int,
) -> tuple:
    """Project-wide chronological sort key for media within an anime.

    Shared by `spoiler_service` (frontier walk), `anime_search_service`
    (media table + timeline chart), and `media_search_service` (related-
    media carousel + 'you are here' marker). Keep call sites going
    through this helper — diverging keys make the three surfaces disagree
    on order, which reads as a bug to users."""
    return (
        season_year or 9999,
        SEASON_ORDER.get(season_name or "", 0),
        mal_id,
    )


def select_note_target_index(media_list: list[Media], *, latest: bool) -> int:
    """Index of the media a bulk note attaches to: the chronologically FIRST
    (`latest=False`) or LAST (`latest=True`) 'main' media, falling back to the first/last
    media overall when the selection has none. Ordered by `chronological_media_key`
    (intrinsic media order, not request/click order), so it's invariant to how the media
    were selected. Shared by bulk watchlist (first — "start here") + bulk rating (last —
    "my take on the latest season") so the two can't drift on how the target is picked.
    Passes the raw `anime_season_name` enum straight through (the str-enum hashes to its
    value), matching `anime_search_service`/`media_search_service`."""
    mains = [(i, m) for i, m in enumerate(media_list) if m.relation_type.value == "main"]
    pool = mains or list(enumerate(media_list))
    pick = max if latest else min
    return pick(
        pool,
        key=lambda im: chronological_media_key(
            im[1].anime_season_year, im[1].anime_season_name, im[1].mal_id
        ),
    )[0]


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
    """Genres that pass the majority rule (>50% of media) for at least one anime —
    the anime-view genre dropdown.

    Projects `DISTINCT genre_name` from the SAME relation the search filter tests
    membership against (`search_filters.anime_genre_majority_relation`), which is
    what makes the dropdown's promise true: every genre offered here can actually
    pass the filter. Duplicating the threshold instead would let the two drift
    into offering genres that return nothing.
    """
    majority = anime_genre_majority_relation()
    stmt = (
        select(distinct(majority.c.genre_name))
        .order_by(majority.c.genre_name)
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


async def _get_anime_aggregated_ranges(db: AsyncSession) -> dict:
    """Get min/max of aggregated values across all anime for filter slider ranges."""
    # Subquery: per-anime aggregates. scored_by uses the relation-weighted mean
    # (Main+Alt only) so the anime-view "scored by" slider max tracks the same
    # value the cards show and the HAVING filter evaluates (search_anime_aggregated).
    anime_agg = (
        select(
            Media.anime_id,
            func.sum(Media.episodes).label("total_episodes"),
            func.sum(Media.total_watch_time).label("total_watch_time"),
            weighted_mean_votes_expr().label("avg_scored_by"),
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


async def fetch_genres(db: AsyncSession) -> list[GenreOut]:
    """All genres with their descriptions, for the frontend's genre-badge
    tooltip lookup. Small static set — fetched once and cached client-side."""
    rows = await genre_dao.get_name_descriptions(db)
    return [GenreOut(name=name, description=description) for name, description in rows]


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
