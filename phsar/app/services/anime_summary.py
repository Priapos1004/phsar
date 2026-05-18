"""Project an Anime ORM row into the admin-card summary shape.

Single source of truth for the `MergeCandidateAnimeSummary` projection
used by both merge_candidate_service.list_pending and
split_candidate_service.list_pending — the two admin queues render the
same side-by-side anime card, so a future field addition (e.g.
airing_status) lands in one place.
"""

from datetime import datetime

from app.models.anime import Anime
from app.schemas.admin_schema import MergeCandidateAnimeSummary


def summarize_anime(anime: Anime, rating_count: int) -> MergeCandidateAnimeSummary:
    """Requires `anime.media` + each media's `media_studio.studio` to be
    pre-loaded by the caller (selectinload). The lazy="raise" config on
    relationships ensures this surfaces fast if missed."""
    studio_names: set[str] = set()
    years: list[int] = []
    aired_from_dates: list[datetime] = []
    for media in anime.media:
        for ms in media.media_studio:
            studio_names.add(ms.studio.name)
        if media.anime_season_year is not None:
            years.append(media.anime_season_year)
        if media.aired_from is not None:
            aired_from_dates.append(media.aired_from)
    return MergeCandidateAnimeSummary(
        uuid=str(anime.uuid),
        title=anime.title,
        name_eng=anime.name_eng,
        name_jap=anime.name_jap,
        media_count=len(anime.media),
        studios=sorted(studio_names),
        earliest_year=min(years) if years else None,
        earliest_aired_from=min(aired_from_dates) if aired_from_dates else None,
        rating_count=rating_count,
    )
