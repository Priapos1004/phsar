"""The recommender's reads around `recommender_compute`, which holds the numerics:
docs/features/recommender.md."""

from datetime import date
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.rating_dao import RatingDAO
from app.daos.recommendation_dao import RecommendationDAO
from app.daos.watchlist_dao import WatchlistDAO
from app.services import recommender_compute as rc
from app.services.filter_service import chronological_media_key

rating_dao = RatingDAO()
recommendation_dao = RecommendationDAO()
watchlist_dao = WatchlistDAO()


class History(NamedTuple):
    """One user's rows as `recommender_compute.ledger` takes them."""
    ratings: list[rc.RatingRow]
    listings: list[rc.ListingRow]
    franchise: dict[int, tuple[bool, int | None]]


async def load_catalogue(db: AsyncSession) -> rc.Catalogue:
    """The catalogue as the map sees it."""
    stars, media = await recommendation_dao.catalogue(db)
    return rc.catalogue(stars, media, chronological_media_key)


async def load_history(db: AsyncSession, user_id: int) -> History:
    ratings = [
        rc.RatingRow(
            r.media_id, r.rating, r.watch_status.value, r.created_at.timestamp(),
            r.watched_at.timestamp() if r.watched_at else None, r.episodes_watched,
        )
        for r in await rating_dao.history(db, user_id)
    ]
    listings = [
        rc.ListingRow(x.media_id, x.priority, x.modified_at.timestamp(), None)
        for x in await watchlist_dao.priorities(db, user_id)
    ]
    return History(ratings, listings, await recommendation_dao.franchise(db, user_id))


async def load_histories(db: AsyncSession) -> dict[int, History]:
    """Every user with ratings: what the harness replays."""
    return {user_id: await load_history(db, user_id) for user_id in sorted(await rating_dao.get_unique_in_field(db, "user_id"))}


async def load_inputs(
    db: AsyncSession, user_id: int, now: float, *, history_start: date | None = None,
) -> tuple[rc.Catalogue, rc.Ledger]:
    """The catalogue and one user's history, as `recommender_compute` takes them to rank at
    `now` (`listed_from`: docs/features/recommender.md, "The ranking")."""
    cat = await load_catalogue(db)
    h = await load_history(db, user_id)
    return cat, rc.ledger(cat, h.ratings, h.listings, history_start, franchise=h.franchise, listed_from=now)
