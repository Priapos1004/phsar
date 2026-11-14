import typing
from datetime import datetime

from sqlalchemy import (
    REAL,
    Table,
    bindparam,
    case,
    cast,
    delete,
    func,
    insert,
    select,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.daos.search_filters import (
    SEASON_KEY,
    anime_genre_majority_relation,
    anime_main_studios,
    anime_mal_figures,
    display_title,
)
from app.daos.watchlist_dao import franchise_signals
from app.models.anime import Anime
from app.models.galaxy import GalaxyGroup, GalaxyStar
from app.models.genre import Genre, GenreType
from app.models.media import (
    AIRING_STATUS_CURRENTLY_AIRING,
    AIRING_STATUS_NOT_YET_AIRED,
    MAIN_STORY_RELATIONS,
    Media,
)
from app.models.ratings import Ratings
from app.models.recommendation import (
    Recommendation,
    RecommendationExposure,
    RecommendationKind,
    RecommendationState,
)
from app.models.tag import Tag
from app.models.user_settings import NameLanguage, UserSettings
from app.models.watchlist_event import WatchlistEvent
from app.services.recommender_compute import ROW, MediaRow, Pick, StarRow

# A recommender genre set is the anime's genres and themes, the tags the app lists together.
_GENRE_KINDS = (GenreType.Genres, GenreType.Themes)


def recommendation_of(user_id: int, anime_id):
    """The join onto the caller's stored ranking from a row carrying `anime_id`: 0 or 1 match,
    so it never fans out — the shape `rating_dao.rating_of` has."""
    return (Recommendation.user_id == user_id) & (Recommendation.anime_id == anime_id)


def for_you_key(*, per_anime: bool) -> tuple:
    """The `for_you` sort's key over `recommendation_of`'s join, and the ties it breaks first:
    docs/features/search.md, "Personal filters and sort"."""
    if per_anime:
        return func.min(Recommendation.rank), ()
    ranked = Recommendation.rank.is_not(None)
    return Recommendation.rank, (case((ranked, SEASON_KEY)).asc().nulls_last(), case((ranked, Media.mal_id)).asc())


def _changes(model, user_id: int):
    """One row of `inputs`' key: count, latest change and the sum of the rows' anime ids."""
    return select(
        func.count().label("n"), func.max(model.modified_at).label("at"), func.sum(Media.anime_id).label("anime"),
    ).join(Media, Media.id == model.media_id).where(model.user_id == user_id).subquery()


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

    async def inputs(self, db: AsyncSession, user_id: int) -> Row:
        """Everything a user's ranking is computed from, short of the date and the model's own
        version: docs/features/recommender.md, "Serving". Carries the recommender settings
        by name (`history_start`, `recommend_hot`)."""
        ratings, log = _changes(Ratings, user_id), _changes(WatchlistEvent, user_id)
        stars = select(func.count().label("n"), func.max(GalaxyStar.id).label("newest")).subquery()
        # One-row aggregates beside the settings row: the join is deliberately on nothing.
        stmt = (
            select(*ratings.c, *log.c, *stars.c, UserSettings.history_start, UserSettings.recommend_hot)
            .select_from(UserSettings).join(ratings, true()).join(log, true()).join(stars, true())
            .where(UserSettings.user_id == user_id)
        )
        return (await db.execute(stmt)).one()

    async def stored_key(self, db: AsyncSession, user_id: int) -> str | None:
        return await db.scalar(select(RecommendationState.inputs_key).where(RecommendationState.user_id == user_id))

    async def lock(self, db: AsyncSession, user_id: int) -> str:
        """The stored key, read under a lock on the user's state row (created empty if
        missing), so two recomputes for one user queue rather than race."""
        await db.execute(
            pg_insert(RecommendationState).values(user_id=user_id, inputs_key="", uuid=func.gen_random_uuid())
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        key = await db.scalar(
            select(RecommendationState.inputs_key).where(RecommendationState.user_id == user_id).with_for_update()
        )
        assert key is not None  # the row exists: inserted above or already there
        return key

    async def replace(self, db: AsyncSession, user_id: int, picks: list[Pick], key: str, now: datetime) -> None:
        """Store a new ranking whole and log the row's exposure against the one it replaces:
        docs/features/recommender.md, "Serving"."""
        replaced = await db.execute(
            delete(Recommendation).where(Recommendation.user_id == user_id)
            .returning(Recommendation.anime_id, Recommendation.rank)
        )
        shown = {anime for anime, rank in replaced.tuples() if rank <= ROW}
        if picks:
            # executemany: one statement per row would cost a round-trip each.
            await db.execute(insert(Recommendation), [
                {"user_id": user_id, "anime_id": p.anime_id, "rank": p.rank, "kind": RecommendationKind(p.kind),
                 "ref_anime_id": p.ref_anime_id, "detail": p.detail}
                for p in picks
            ])
        top = [p for p in picks if p.rank <= ROW]
        stays = [p for p in top if p.anime_id in shown]
        if stays:
            exposure = typing.cast(Table, RecommendationExposure.__table__)
            latest = select(func.max(exposure.c.id)).where(
                exposure.c.user_id == user_id, exposure.c.anime_id == bindparam("anime"),
            ).scalar_subquery()
            await db.execute(
                update(exposure).where(exposure.c.id == latest)
                .values(best_rank=func.least(exposure.c.best_rank, bindparam("rank")), modified_at=now),
                [{"anime": p.anime_id, "rank": p.rank} for p in stays],
            )
        if entered := [p for p in top if p.anime_id not in shown]:
            await db.execute(insert(RecommendationExposure), [
                {"user_id": user_id, "anime_id": p.anime_id, "best_rank": p.rank, "kind": RecommendationKind(p.kind),
                 "created_at": now, "modified_at": now}
                for p in entered
            ])
        await db.execute(update(RecommendationState).where(RecommendationState.user_id == user_id).values(inputs_key=key))

    async def ranked_ids(self, db: AsyncSession, user_id: int, *, per_anime: bool) -> set[int]:
        """The anime the caller's ranking holds or, per media, their media."""
        ranked = select(Recommendation.anime_id).where(Recommendation.user_id == user_id)
        if not per_anime:
            ranked = select(Media.id).where(Media.anime_id.in_(ranked))
        return set((await db.execute(ranked)).scalars())

    async def reasons(
        self, db: AsyncSession, user_id: int, ids: list[int], *, per_anime: bool, name_language: NameLanguage,
    ) -> dict[int, tuple[RecommendationKind, str | None]]:
        """Each of `ids`' reason and what it names: the reference anime's title as the caller
        reads it, else the pick's detail, else for an explore pick its region's name."""
        ref = aliased(Anime)
        region = aliased(GalaxyGroup)
        owner = Media.id if not per_anime else Recommendation.anime_id
        stmt = (
            select(owner, Recommendation.kind, func.coalesce(
                display_title(ref, name_language), Recommendation.detail, region.name, region.auto_name,
            ))
            .select_from(Recommendation)
            .outerjoin(ref, ref.id == Recommendation.ref_anime_id)
            .outerjoin(GalaxyStar, (GalaxyStar.anime_id == Recommendation.anime_id) & (Recommendation.kind == RecommendationKind.EXPLORE))
            .outerjoin(region, region.id == GalaxyStar.region_id)
            .where(Recommendation.user_id == user_id)
        )
        if not per_anime:
            stmt = stmt.join(Media, Media.anime_id == Recommendation.anime_id)
        stmt = stmt.where(owner.in_(ids))
        return {id_: (kind, name) for id_, kind, name in (await db.execute(stmt)).tuples().all()}

    async def watchlist_events(self, db: AsyncSession, user_id: int) -> list[Row]:
        """The user's watchlist history in order, each event with its list's name."""
        stmt = (
            select(WatchlistEvent.media_id, WatchlistEvent.kind, WatchlistEvent.priority, Tag.name.label("tag"), WatchlistEvent.at)
            .outerjoin(Tag, Tag.id == WatchlistEvent.tag_id)
            .where(WatchlistEvent.user_id == user_id)
            .order_by(WatchlistEvent.at, WatchlistEvent.id)
        )
        return list((await db.execute(stmt)).all())

    async def log_start(self, db: AsyncSession) -> datetime | None:
        """When the watchlist's log began: its history is whole from here on."""
        # Its first row is a seed row, logged with every other: the primary key finds it.
        return await db.scalar(select(WatchlistEvent.created_at).order_by(WatchlistEvent.id).limit(1))
