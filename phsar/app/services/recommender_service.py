"""The recommender's reads around `recommender_compute`, which holds the numerics:
docs/features/recommender.md."""

import hashlib
import math
import time
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import NamedTuple

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.rating_dao import RatingDAO
from app.daos.recommendation_dao import RecommendationDAO
from app.daos.search_filters import utc_today
from app.schemas.media_filter_schema import CatalogueSearchFilters, SortKey
from app.services import recommender_compute as rc
from app.services.filter_service import chronological_media_key

rating_dao = RatingDAO()
recommendation_dao = RecommendationDAO()


class History(NamedTuple):
    """One user's rows as `recommender_compute.ledger` takes them."""
    ratings: list[rc.RatingRow]
    listings: list[rc.ListingRow]
    franchise: dict[int, tuple[bool, int | None]]


async def load_catalogue(db: AsyncSession) -> rc.Catalogue:
    """The catalogue as the map sees it, built in a thread: it is CPU work."""
    stars, media = await recommendation_dao.catalogue(db)
    return await anyio.to_thread.run_sync(rc.catalogue, stars, media, chronological_media_key)


async def load_log_start(db: AsyncSession) -> float:
    """When the watchlist's log began, as `ledger`'s `listed_from`: inf without one."""
    start = await recommendation_dao.log_start(db)
    return start.timestamp() if start else math.inf


async def _ratings(db: AsyncSession, user_id: int) -> list[rc.RatingRow]:
    return [
        rc.RatingRow(
            r.media_id, r.rating, r.watch_status.value, r.created_at.timestamp(),
            r.watched_at.timestamp() if r.watched_at else None, r.episodes_watched,
        )
        for r in await rating_dao.history(db, user_id)
    ]


async def load_history(db: AsyncSession, user_id: int) -> History:
    ratings = await _ratings(db, user_id)
    listings = rc.listings_from_log([
        (e.media_id, e.kind.value, e.priority, e.tag, e.at.timestamp())
        for e in await recommendation_dao.watchlist_events(db, user_id)
    ])
    return History(ratings, listings, await recommendation_dao.franchise(db, user_id))


async def load_histories(db: AsyncSession) -> dict[int, History]:
    """Every user with ratings: what the harness replays."""
    return {user_id: await load_history(db, user_id) for user_id in sorted(await rating_dao.get_unique_in_field(db, "user_id"))}


async def load_inputs(
    db: AsyncSession, user_id: int, *, history_start: date | None = None,
) -> tuple[rc.Catalogue, rc.Ledger]:
    """The catalogue and one user's history, as `recommender_compute` takes them."""
    cat = await load_catalogue(db)
    h = await load_history(db, user_id)
    led = partial(rc.ledger, cat, h.ratings, h.listings, history_start, franchise=h.franchise,
                  listed_from=await load_log_start(db))
    return cat, await anyio.to_thread.run_sync(led)


async def ensure_fresh(db: AsyncSession, user_id: int) -> None:
    """Recompute the user's stored ranking when anything it reads has changed since:
    docs/features/recommender.md, "Serving". Commits whenever it took the lock."""
    inputs = await recommendation_dao.inputs(db, user_id)
    key = hashlib.sha256(repr((rc.version(), utc_today().isoformat(), tuple(inputs))).encode()).hexdigest()
    if await recommendation_dao.stored_key(db, user_id) == key:
        return
    if await recommendation_dao.lock(db, user_id) == key:  # a concurrent request recomputed it
        await db.commit()  # releases the lock
        return
    cat, led = await load_inputs(db, user_id, history_start=inputs.history_start)
    now = time.time()
    picks = await anyio.to_thread.run_sync(partial(rc.recommend, cat, led, now, hot=inputs.recommend_hot))
    await recommendation_dao.replace(db, user_id, picks, key, datetime.fromtimestamp(now, UTC))
    await db.commit()


async def ensure_fresh_for(db: AsyncSession, user_id: int, sort: SortKey | None, filters: CatalogueSearchFilters) -> None:
    """`ensure_fresh` for a search that reads the ranking."""
    if sort == SortKey.FOR_YOU or filters.recommended is not None:
        await ensure_fresh(db, user_id)


async def detected_history_start(db: AsyncSession, user_id: int) -> date | None:
    """The day the user's own watching order starts by the import rule, ignoring any date
    they chose."""
    cat = await load_catalogue(db)
    led = await anyio.to_thread.run_sync(rc.ledger, cat, await _ratings(db, user_id), [])
    return rc.EPOCH + timedelta(days=led.start) if led.start is not None else None
