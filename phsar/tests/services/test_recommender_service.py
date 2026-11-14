"""`recommender_service` and the stored ranking around it, mostly against a real database. The
ranking itself is stubbed: what it computes is `recommender_compute`'s, tested there."""

import asyncio
import time
from datetime import date

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.daos.search_filters import SEASON_KEY
from app.daos.user_dao import UserDAO
from app.models.anime import Anime
from app.models.galaxy import GalaxyFit, GalaxyGroup, GalaxyStar
from app.models.media import Media, SeasonType
from app.models.ratings import Ratings, WatchStatus
from app.models.recommendation import (
    Recommendation,
    RecommendationExposure,
    RecommendationState,
)
from app.models.tag import Tag
from app.models.user_settings import UserSettings
from app.models.users import Users
from app.models.watchlist import Watchlist
from app.models.watchlist_event import WatchlistEvent
from app.services import recommender_compute as rc
from app.services import recommender_service
from app.services.filter_service import chronological_media_key
from tests._helpers import make_user, media_kwargs


class Ranking:
    """Stands in for `recommender_compute.recommend`: returns `picks` after `delay` seconds and
    counts its calls."""

    def __init__(self, monkeypatch, delay: float = 0.0):
        self.calls = 0
        self.delay = delay
        self.picks: list[rc.Pick] = []
        monkeypatch.setattr(rc, "recommend", self)

    def __call__(self, *args, **kwargs):
        self.calls += 1
        time.sleep(self.delay)
        return self.picks

    def rank(self, *anime_ids):
        self.picks = [rc.Pick(a, i, "popular", None, None) for i, a in enumerate(anime_ids, start=1)]


@pytest.fixture
async def world(db_session, monkeypatch):
    """A user with settings and a list, and three one-media anime."""
    user = await make_user(db_session, "rec-user")
    tag = Tag(user_id=user.id, name="Watchlist", is_default=True)
    db_session.add_all([UserSettings(user_id=user.id), tag])
    anime = [Anime(mal_id=-92000 - i, title=f"A-9200{i}-rec") for i in range(3)]
    db_session.add_all(anime)
    await db_session.flush()
    media = [Media(**media_kwargs(a.id, a.mal_id)) for a in anime]
    db_session.add_all(media)
    await db_session.flush()
    return db_session, user, tag, anime, media, Ranking(monkeypatch)


async def test_the_ranking_recomputes_once_per_change_of_its_inputs(world, monkeypatch):
    db, user, tag, anime, media, ranking = world

    async def fresh():
        await recommender_service.ensure_fresh(db, user.id)
        return ranking.calls

    assert await fresh() == 1
    assert await fresh() == 1
    db.add(Ratings(user_id=user.id, media_id=media[0].id, rating=7.0, watch_status=WatchStatus.completed))
    await db.flush()
    assert await fresh() == 2
    db.add(Watchlist(user_id=user.id, media_id=media[1].id, tag_id=tag.id, priority=2))
    await db.flush()
    assert await fresh() == 3
    await db.execute(update(UserSettings).where(UserSettings.user_id == user.id).values(recommend_hot=False))
    assert await fresh() == 4
    await db.execute(update(UserSettings).where(UserSettings.user_id == user.id).values(history_start=date(2026, 1, 1)))
    assert await fresh() == 5
    # A merge moves a rated media to another anime without touching the rating.
    await db.execute(update(Media).where(Media.id == media[0].id).values(anime_id=anime[2].id))
    assert await fresh() == 6
    fit = GalaxyFit(models=b"", params={})
    db.add(fit)
    await db.flush()
    sector = GalaxyGroup(fit_id=fit.id, number=0, auto_name="Sector", x=0.0, y=0.0)
    db.add(sector)
    await db.flush()
    db.add(GalaxyStar(
        anime_id=anime[1].id, sector_id=sector.id, region_id=sector.id, x=0.0, y=0.0, z10=[0.0] * 10,
        features=[0.0], uncertainty=0.0, between=False, trained=True,
    ))
    await db.flush()
    assert await fresh() == 7
    monkeypatch.setattr(recommender_service, "utc_today", lambda: date(2099, 1, 1))
    assert await fresh() == 8
    assert await fresh() == 8


async def _stretches(db, user):
    rows = (await db.execute(
        select(RecommendationExposure.anime_id, RecommendationExposure.best_rank, RecommendationExposure.modified_at)
        .where(RecommendationExposure.user_id == user.id).order_by(RecommendationExposure.id)
    )).all()
    return [(a, r) for a, r, _ in rows], {a: at for a, _, at in rows}


async def test_the_row_logs_one_stretch_per_spell_in_it_not_per_recompute(world, monkeypatch):
    db, user, _, anime, _, ranking = world
    a, b, c = (x.id for x in anime)
    day = iter(date(2099, 1, d) for d in range(1, 10))

    async def recompute():
        today = next(day)
        monkeypatch.setattr(recommender_service, "utc_today", lambda: today)
        await recommender_service.ensure_fresh(db, user.id)

    ranking.rank(a, b)
    await recompute()
    opened, first = await _stretches(db, user)
    assert opened == [(a, 1), (b, 2)]
    ranking.rank(b, a)
    await recompute()
    kept, later = await _stretches(db, user)
    assert kept == [(a, 1), (b, 1)]
    assert later[a] > first[a]
    ranking.rank(c, a)
    await recompute()
    assert (await _stretches(db, user))[0] == [(a, 1), (b, 1), (c, 1)]
    ranking.rank(b, a, c)
    await recompute()
    assert (await _stretches(db, user))[0] == [(a, 1), (b, 1), (c, 1), (b, 1)]


async def test_a_deleted_account_leaves_no_recommender_rows(world):
    db, user, tag, anime, media, ranking = world
    db.add(Watchlist(user_id=user.id, media_id=media[0].id, tag_id=tag.id, priority=1))
    ranking.rank(anime[0].id, anime[1].id)
    await recommender_service.ensure_fresh(db, user.id)
    await UserDAO().delete(db, user)
    for model in (Recommendation, RecommendationState, RecommendationExposure, WatchlistEvent):
        assert await db.scalar(select(func.count()).select_from(model).where(model.user_id == user.id)) == 0


async def test_the_history_reads_the_watchlists_log(world):
    """Listings come from the log's events, and the history counts as whole from the
    log's first row."""
    db, user, tag, _, media, _ = world
    db.add(Watchlist(user_id=user.id, media_id=media[0].id, tag_id=tag.id, priority=2))
    await db.flush()
    await db.execute(update(Watchlist).where(Watchlist.media_id == media[0].id).values(priority=1))
    history = await recommender_service.load_history(db, user.id)
    assert [(x.media_id, x.priority, x.until) for x in history.listings] == [(media[0].id, 1, None)]
    start = await db.scalar(select(func.min(WatchlistEvent.created_at)))
    assert await recommender_service.load_log_start(db) == start.timestamp()


async def test_the_sql_watching_order_matches_the_projects(db_session):
    """`SEASON_KEY` with nulls last, then MAL id — the order `for_you_key` gives one anime's
    media — orders as `chronological_media_key` does."""
    anime = Anime(mal_id=-93000, title="A-93000-chrono")
    db_session.add(anime)
    await db_session.flush()
    seasons = [(2021, SeasonType.Spring, 5), (2020, SeasonType.Fall, 9), (None, None, 1), (2021, SeasonType.Winter, 7),
               (2021, SeasonType.Spring, 3)]
    for year, season, mal in seasons:
        db_session.add(Media(**media_kwargs(anime.id, -93000 - mal, anime_season_year=year, anime_season_name=season)))
    await db_session.flush()
    rows = (await db_session.execute(
        select(Media.anime_season_year, Media.anime_season_name, Media.mal_id)
        .where(Media.anime_id == anime.id).order_by(SEASON_KEY.nulls_last(), Media.mal_id)
    )).all()
    assert list(rows) == sorted(rows, key=lambda r: chronological_media_key(r[0], r[1], r[2]))


async def test_concurrent_recomputes_for_one_user_compute_once(db_engine, monkeypatch):
    """Two requests finding a stored ranking stale at once: the second waits on the first's
    lock and finds it fresh. Runs on committed rows, so it cleans up after itself."""
    ranking = Ranking(monkeypatch, delay=0.3)
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        user = await make_user(db, "rec-concurrent")
        db.add(UserSettings(user_id=user.id))
        await db.commit()
    try:
        async def request():
            async with sessions() as db:
                await recommender_service.ensure_fresh(db, user.id)
        await request()
        monkeypatch.setattr(recommender_service, "utc_today", lambda: date(2099, 1, 1))
        await asyncio.gather(request(), request())
        assert ranking.calls == 2
    finally:
        async with sessions() as db:
            await db.execute(delete(Users).where(Users.id == user.id))
            await db.commit()


def test_listings_follow_the_log():
    """An add or a change opens a stretch, closing the one before; a removal closes it."""
    t = 1_000.0
    events = [(1, "added", 3, "A", t), (2, "added", 2, None, t + 1), (1, "changed", 1, "A", t + 2),
              (2, "removed", 2, None, t + 3), (1, "removed", 1, "A", t + 4), (1, "added", 2, "B", t + 5)]
    assert rc.listings_from_log(events) == [
        rc.ListingRow(1, 3, t, t + 2, "A"), rc.ListingRow(2, 2, t + 1, t + 3, None),
        rc.ListingRow(1, 1, t + 2, t + 4, "A"), rc.ListingRow(1, 2, t + 5, None, "B"),
    ]
