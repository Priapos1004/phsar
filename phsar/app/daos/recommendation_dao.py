from sqlalchemy import REAL, cast, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.search_filters import (
    SEASON_KEY,
    anime_genre_majority_relation,
    anime_main_studios,
    anime_mal_figures,
)
from app.daos.watchlist_dao import franchise_signals
from app.models.galaxy import GalaxyStar
from app.models.genre import Genre, GenreType
from app.models.media import (
    AIRING_STATUS_CURRENTLY_AIRING,
    AIRING_STATUS_NOT_YET_AIRED,
    MAIN_STORY_RELATIONS,
    Media,
)
from app.services.recommender_compute import MediaRow, StarRow

# A recommender genre set is the anime's genres and themes, the tags the app lists together.
_GENRE_KINDS = (GenreType.Genres, GenreType.Themes)


class RecommendationDAO:
    async def catalogue(self, db: AsyncSession) -> tuple[list[StarRow], list[MediaRow]]:
        """Every star with what the app says of its anime — MAL score and votes as the card
        shows them, the majority genres, the main story's studios — and every media of a
        starred anime, as the plain rows `recommender_compute` reads. The vector arrives as
        `real[]`, which converts an order of magnitude faster than pgvector's text form,
        parsed in Python."""
        on_map = select(GalaxyStar.anime_id)
        figures = {anime_id: (score, votes) for anime_id, score, votes in (await db.execute(anime_mal_figures(on_map))).all()}
        majority = anime_genre_majority_relation()
        genres: dict[int, list[str]] = {}
        for anime_id, name in (await db.execute(
            select(majority.c.anime_id, majority.c.genre_name)
            .join(Genre, Genre.name == majority.c.genre_name)
            .where(Genre.genre_type.in_(_GENRE_KINDS), majority.c.anime_id.in_(on_map))
        )).all():
            genres.setdefault(anime_id, []).append(name)
        studios = dict((await db.execute(select(anime_main_studios(on_map)))).tuples().all())
        stars = [
            StarRow(
                anime_id, list(features), uncertainty, sector, region,
                *figures.get(anime_id, (None, None)),
                genres=tuple(genres.get(anime_id, ())), studios=tuple(studios.get(anime_id, ())),
            )
            for anime_id, features, uncertainty, sector, region in (await db.execute(
                select(
                    GalaxyStar.anime_id, cast(GalaxyStar.features, ARRAY(REAL)), GalaxyStar.uncertainty,
                    GalaxyStar.sector_id, GalaxyStar.region_id,
                ).order_by(GalaxyStar.anime_id)
            )).all()
        ]
        rows = (await db.execute(
            select(
                Media.id, Media.anime_id, Media.mal_id, Media.relation_type, Media.media_type,
                Media.episodes, Media.duration_seconds, Media.total_watch_time,
                Media.anime_season_year, Media.anime_season_name, SEASON_KEY.label("season_key"),
                Media.aired_from, Media.aired_to, Media.airing_status,
            ).where(Media.anime_id.in_(on_map))
        )).all()
        media = [
            MediaRow(
                media_id=m.id, anime_id=m.anime_id, mal_id=m.mal_id,
                main=m.relation_type in MAIN_STORY_RELATIONS, media_type=m.media_type.value,
                episodes=m.episodes, duration_seconds=m.duration_seconds, total_watch_time=m.total_watch_time,
                season_year=m.anime_season_year,
                season_name=m.anime_season_name.value if m.anime_season_name else None,
                season_key=m.season_key, aired_from=m.aired_from, aired_to=m.aired_to,
                unaired=m.airing_status == AIRING_STATUS_NOT_YET_AIRED,
                airing=m.airing_status == AIRING_STATUS_CURRENTLY_AIRING,
            )
            for m in rows
        ]
        return stars, media

    async def franchise(self, db: AsyncSession, user_id: int) -> dict[int, tuple[bool, int | None]]:
        """`franchise_signals` for every starred anime, listed or not: the readiness verdict's
        franchise inputs, from the query the watchlist's own verdict reads."""
        signals = franchise_signals(select(GalaxyStar.anime_id), user_id)
        stmt = select(signals.c.anime_id, signals.c.franchise_airing, signals.c.franchise_upcoming_key)
        return {anime_id: (bool(airing), key) for anime_id, airing, key in (await db.execute(stmt)).all()}
