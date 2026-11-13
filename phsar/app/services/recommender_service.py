"""The recommender's reads around `recommender_compute`, which holds the numerics:
docs/features/recommender.md."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.rating_dao import RatingDAO
from app.daos.recommendation_dao import RecommendationDAO
from app.daos.watchlist_dao import WatchlistDAO
from app.services import recommender_compute as rc
from app.services.filter_service import chronological_media_key

rating_dao = RatingDAO()
recommendation_dao = RecommendationDAO()
watchlist_dao = WatchlistDAO()


async def load_inputs(
    db: AsyncSession, user_id: int, *, history_start: date | None = None,
) -> tuple[rc.Catalogue, rc.Ledger]:
    """The catalogue as the map sees it and the user's history, as `recommender_compute`
    takes them."""
    stars, media = await recommendation_dao.catalogue(db)
    cat = rc.catalogue(stars, media, chronological_media_key)
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
    franchise = await recommendation_dao.franchise(db, user_id)
    return cat, rc.ledger(cat, ratings, listings, history_start, franchise=franchise)
