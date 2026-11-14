"""The recommender's reads around `recommender_compute`, which holds the numerics:
docs/features/recommender.md."""

import hashlib
import math
import time
from datetime import UTC, datetime
from functools import partial
from typing import NamedTuple
from uuid import UUID

import anyio
import numpy as np
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.rating_dao import RatingDAO
from app.daos.recommendation_dao import RecommendationDAO
from app.daos.search_filters import utc_today
from app.exceptions import RatingNotFoundError
from app.schemas.media_filter_schema import CatalogueSearchFilters, SortKey
from app.schemas.rating_schema import HistoryStart, HistoryStartRating
from app.services import recommender_compute as rc
from app.services.filter_service import chronological_media_key
from app.services.user_settings_service import settings_row

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


def _rating_row(r: Row) -> rc.RatingRow:
    return rc.RatingRow(
        r.media_id, r.rating, r.watch_status.value, r.created_at.timestamp(),
        r.watched_at.timestamp() if r.watched_at else None, r.episodes_watched,
    )


async def load_history(db: AsyncSession, user_id: int) -> History:
    ratings = [_rating_row(r) for r in await rating_dao.history(db, user_id)]
    listings = rc.listings_from_log([
        (e.media_id, e.kind.value, e.priority, e.tag, e.at.timestamp())
        for e in await recommendation_dao.watchlist_events(db, user_id)
    ])
    return History(ratings, listings, await recommendation_dao.franchise(db, user_id))


async def load_histories(db: AsyncSession) -> dict[int, History]:
    """Every user with ratings: what the harness replays."""
    return {user_id: await load_history(db, user_id) for user_id in sorted(await rating_dao.get_unique_in_field(db, "user_id"))}


async def load_inputs(
    db: AsyncSession, user_id: int, *, history_start: int | None = None,
) -> tuple[rc.Catalogue, rc.Ledger]:
    """The catalogue and one user's history, as `recommender_compute` takes them;
    `history_start` as `RecommendationDAO.inputs` carries it."""
    cat = await load_catalogue(db)
    h = await load_history(db, user_id)
    override = next((rc.event_time(r) for r in h.ratings if r.media_id == history_start), None)
    led = partial(rc.ledger, cat, h.ratings, h.listings, override, franchise=h.franchise,
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


async def history_start(db: AsyncSession, user_id: int) -> HistoryStart:
    """`/ratings/history-start`'s answer: the import rule over the user's ratings alone, without
    the catalogue the ranking reads. Only anime on the map count, as they do for the ranking."""
    chosen = (await settings_row(db, user_id)).history_start_rating_id
    timed = sorted(
        ((rc.event_time(_rating_row(r)), r) for r in await rating_dao.history(db, user_id)),
        key=lambda tr: (tr[0], tr[1].id),
    )
    mapped = [(t, r) for t, r in timed if r.on_map]

    def column(value) -> np.ndarray:
        return np.array([value(r) for _, r in mapped], dtype=float)

    hours = rc.watch_hours(
        column(lambda r: math.nan if r.episodes_watched is None else r.episodes_watched),
        column(lambda r: r.episodes or math.nan),
        column(lambda r: r.duration_seconds or math.nan),
    )
    keep, _ = rc.natural_ratings(np.array([t for t, _ in mapped], dtype=float), hours, [r.anime_id for _, r in mapped], None)
    return HistoryStart(
        detected=next((r.uuid for (_, r), natural in zip(mapped, keep.tolist(), strict=True) if natural), None),
        chosen=next((r.uuid for _, r in timed if r.id == chosen), None),
        ratings=[
            HistoryStartRating(
                uuid=r.uuid, title=r.title, name_eng=r.name_eng, name_jap=r.name_jap, cover_image=r.cover_image,
                at=datetime.fromtimestamp(t, UTC),
            )
            for t, r in timed
        ],
    )


async def choose_history_start(db: AsyncSession, user_id: int, rating_uuid: UUID | None) -> HistoryStart:
    """Start the user's own order at one of their ratings, or, with None, at the detected one."""
    settings = await settings_row(db, user_id)
    rating_id = None
    if rating_uuid is not None:
        rating = await rating_dao.get_by_field(db, uuid=rating_uuid, user_id=user_id)
        if rating is None:
            raise RatingNotFoundError(str(rating_uuid))
        rating_id = rating.id
    settings.history_start_rating_id = rating_id
    await db.commit()
    return await history_start(db, user_id)
