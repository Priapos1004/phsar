import logging
from collections import Counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.anime_dao import AnimeDAO
from app.exceptions import AnimeNotFoundByUuidError
from app.models.media import Media
from app.schemas.anime_schema import (
    AnimeDetail,
    AnimeMediaItem,
    AnimeSearchResult,
    MediaTypeSummary,
    RelationTypeSummary,
)
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.services.filter_service import SEASON_ORDER

logger = logging.getLogger(__name__)

anime_dao = AnimeDAO()


def _compute_airing_status(statuses: list[str]) -> tuple[str, bool]:
    """Compute a single airing status from a list of per-media statuses.
    Returns (primary_status, has_upcoming)."""
    has_current = "Currently Airing" in statuses
    has_finished = "Finished Airing" in statuses
    has_upcoming = "Not yet aired" in statuses

    if has_current:
        primary = "Currently Airing"
    elif has_finished:
        primary = "Finished Airing"
    else:
        primary = "Not yet aired"

    show_upcoming = has_upcoming and (has_current or has_finished)
    return primary, show_upcoming


def _compute_season_range(
    seasons: list[tuple[str, int]],
) -> tuple[str | None, str | None]:
    """Compute start and end season strings from a list of (season_name, year) tuples.
    Returns (start, end) where end is None if same as start."""
    if not seasons:
        return None, None
    sorted_seasons = sorted(seasons, key=lambda s: (s[1], SEASON_ORDER.get(s[0], 0)))
    start = f"{sorted_seasons[0][0]} {sorted_seasons[0][1]}"
    end = f"{sorted_seasons[-1][0]} {sorted_seasons[-1][1]}"
    if start == end:
        return start, None
    return start, end


def _compute_anime_aggregates(media_list: list[Media]) -> dict:
    """Compute aggregated metadata from a list of media belonging to one anime.
    Used by both search results and detail page."""
    genre_counts: Counter[str] = Counter()
    all_studios: set[str] = set()
    all_statuses: list[str] = []
    all_seasons: list[tuple[str, int]] = []
    relation_type_counts: Counter[str] = Counter()
    media_type_counts: Counter[str] = Counter()
    scores: list[float] = []
    scored_by_values: list[int] = []
    total_episodes = 0
    total_watch_time = 0
    max_age_rating: int | None = None

    for m in media_list:
        genres = [mg.genre.name for mg in m.media_genre]
        studios = [ms.studio.name for ms in m.media_studio]

        for g in genres:
            genre_counts[g] += 1
        all_studios.update(studios)
        all_statuses.append(m.airing_status)
        relation_type_counts[m.relation_type.value] += 1
        media_type_counts[m.media_type.value] += 1

        if m.anime_season_name and m.anime_season_year:
            all_seasons.append((m.anime_season_name.value, m.anime_season_year))
        if m.score is not None:
            scores.append(m.score)
        scored_by_values.append(m.scored_by)
        if m.episodes:
            total_episodes += m.episodes
        if m.total_watch_time:
            total_watch_time += m.total_watch_time
        if m.age_rating_numeric is not None:
            max_age_rating = max(max_age_rating or 0, m.age_rating_numeric)

    media_count = len(media_list)
    majority_threshold = media_count / 2
    majority_genres = sorted(g for g, c in genre_counts.items() if c > majority_threshold)

    airing_status, has_upcoming = _compute_airing_status(all_statuses)
    season_start, season_end = _compute_season_range(all_seasons)

    return {
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "avg_scored_by": round(sum(scored_by_values) / len(scored_by_values)) if scored_by_values else 0,
        "total_episodes": total_episodes or None,
        "total_watch_time": total_watch_time or None,
        "media_count": media_count,
        "relation_types": [
            RelationTypeSummary(relation_type=rt, count=c)
            for rt, c in relation_type_counts.most_common()
        ],
        "media_types": [
            MediaTypeSummary(media_type=mt, count=c)
            for mt, c in media_type_counts.most_common()
        ],
        "genres": majority_genres,
        "studios": sorted(all_studios),
        "season_start": season_start,
        "season_end": season_end,
        "airing_status": airing_status,
        "has_upcoming": has_upcoming,
        "age_rating_numeric": max_age_rating,
    }


def _media_to_anime_media_item(m: Media) -> AnimeMediaItem:
    return AnimeMediaItem(
        uuid=m.uuid,
        title=m.title,
        name_eng=m.name_eng,
        cover_image=m.cover_image,
        media_type=m.media_type.value,
        relation_type=m.relation_type.value,
        score=m.score,
        scored_by=m.scored_by,
        episodes=m.episodes,
        airing_status=m.airing_status,
        anime_season_name=m.anime_season_name.value if m.anime_season_name else None,
        anime_season_year=m.anime_season_year,
        total_watch_time=m.total_watch_time,
        age_rating_numeric=m.age_rating_numeric,
        genres=[mg.genre.name for mg in m.media_genre],
        studios=[ms.studio.name for ms in m.media_studio],
    )


def anime_title_texts(anime) -> list[str]:
    """Build the list of title texts for embedding generation from an Anime object."""
    return [anime.title, anime.name_eng, anime.name_jap, *(anime.other_names or [])]


async def search_anime_by_query(
    db: AsyncSession,
    query: str,
    filters: MediaSearchFilters,
    search_type: SearchType,
) -> list[AnimeSearchResult]:
    anime_list = await anime_dao.search_anime_aggregated(
        db=db, query=query, filters=filters, search_type=search_type,
    )

    results = []
    for anime in anime_list:
        agg = _compute_anime_aggregates(list(anime.media))
        results.append(AnimeSearchResult(
            uuid=anime.uuid,
            title=anime.title,
            name_eng=anime.name_eng,
            name_jap=anime.name_jap,
            cover_image=anime.cover_image,
            **agg,
        ))

    return results


async def get_anime_detail(db: AsyncSession, anime_uuid: UUID) -> AnimeDetail:
    anime = await anime_dao.get_by_uuid_with_all_media(db, anime_uuid)
    if not anime:
        raise AnimeNotFoundByUuidError(str(anime_uuid))

    media_list = list(anime.media)
    agg = _compute_anime_aggregates(media_list)
    media_items = [_media_to_anime_media_item(m) for m in media_list]

    return AnimeDetail(
        uuid=anime.uuid,
        title=anime.title,
        name_eng=anime.name_eng,
        name_jap=anime.name_jap,
        other_names=anime.other_names or [],
        description=anime.description,
        cover_image=anime.cover_image,
        media=media_items,
        **agg,
    )
