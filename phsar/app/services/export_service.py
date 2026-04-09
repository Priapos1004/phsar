from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.media import Media
from app.models.ratings import Ratings
from app.models.watchlist import Watchlist
from app.models.watchlist_tag import WatchlistTag


def _rating_to_dict(r: Ratings) -> dict:
    media = r.media
    anime = media.anime
    d = {
        "anime_title": anime.title,
        "media_title": media.title,
        "media_type": media.media_type.value if media.media_type else None,
        "relation_type": media.relation_type.value if media.relation_type else None,
        "episodes": media.episodes,
        "rating": r.rating,
        "dropped": r.dropped,
        "episodes_watched": r.episodes_watched,
        "note": r.note,
        "rated_at": r.created_at.isoformat() if r.created_at else None,
        "rating_updated_at": r.modified_at.isoformat() if r.modified_at else None,
    }
    for attr in Ratings.ATTRIBUTE_FIELDS:
        val = getattr(r, attr, None)
        d[attr] = val.value if val is not None else None
    return d


def _watchlist_to_dict(w: Watchlist) -> dict:
    media = w.media
    anime = media.anime
    tags = [wt.tag.name for wt in w.watchlist_tag]
    return {
        "anime_title": anime.title,
        "media_title": media.title,
        "media_type": media.media_type.value if media.media_type else None,
        "priority": w.priority,
        "note": w.note,
        "tags": tags,
        "added_at": w.created_at.isoformat() if w.created_at else None,
    }


async def fetch_export_data(db: AsyncSession, user_id: int) -> dict:
    """Fetch all ratings and watchlist entries for a user with related media/anime info."""
    ratings_stmt = (
        select(Ratings)
        .filter_by(user_id=user_id)
        .options(selectinload(Ratings.media).selectinload(Media.anime))
        .order_by(Ratings.modified_at.desc())
    )
    ratings_result = await db.execute(ratings_stmt)
    ratings = ratings_result.scalars().all()

    watchlist_stmt = (
        select(Watchlist)
        .filter_by(user_id=user_id)
        .options(
            selectinload(Watchlist.media).selectinload(Media.anime),
            selectinload(Watchlist.watchlist_tag).selectinload(WatchlistTag.tag),
        )
        .order_by(Watchlist.created_at.desc())
    )
    watchlist_result = await db.execute(watchlist_stmt)
    watchlist_entries = watchlist_result.scalars().all()

    return {
        "ratings": [_rating_to_dict(r) for r in ratings],
        "watchlist": [_watchlist_to_dict(w) for w in watchlist_entries],
    }
