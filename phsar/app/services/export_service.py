from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.media import Media
from app.models.ratings import Ratings
from app.models.user_settings import NameLanguage
from app.models.watchlist import Watchlist
from app.models.watchlist_tag import WatchlistTag


def _resolve_name(
    title: str,
    name_eng: str | None,
    name_jap: str | None,
    language: NameLanguage,
) -> str | None:
    """Return localized name if it differs from romaji title, else None."""
    if language == NameLanguage.romaji:
        return None
    if language == NameLanguage.japanese and name_jap:
        resolved = name_jap
    elif language == NameLanguage.english and name_eng:
        resolved = name_eng
    else:
        resolved = name_eng or None
    if resolved and resolved != title:
        return resolved
    return None


def _media_columns(media: Media, name_language: NameLanguage) -> dict:
    """Build the anime/media catalog columns for a row."""
    anime = media.anime
    row: dict = {
        "anime_title": anime.title,
    }
    anime_name = _resolve_name(anime.title, anime.name_eng, anime.name_jap, name_language)
    if anime_name is not None:
        row["anime_name"] = anime_name
    row["title"] = media.title
    media_name = _resolve_name(media.title, media.name_eng, media.name_jap, name_language)
    if media_name is not None:
        row["name"] = media_name
    # --- Identifiers ---
    row["anime_mal_id"] = anime.mal_id
    row["mal_id"] = media.mal_id
    # --- Media metadata ---
    row["type"] = media.media_type.value if media.media_type else None
    row["relation"] = media.relation_type.value if media.relation_type else None
    row["episodes"] = media.episodes
    row["episode_duration_seconds"] = media.duration_seconds
    row["season"] = media.anime_season_name.value if media.anime_season_name else None
    row["season_year"] = media.anime_season_year
    row["age_rating"] = media.age_rating
    row["mal_score"] = media.score
    row["mal_scored_by"] = media.scored_by
    return row


def _rating_columns(r: Ratings) -> dict:
    d = {
        "rating": r.rating,
        "dropped": r.dropped,
        "episodes_watched": r.episodes_watched,
        "rating_note": r.note,
        "rated_at": r.created_at.isoformat() if r.created_at else None,
        "rating_updated_at": r.modified_at.isoformat() if r.modified_at else None,
    }
    for attr in Ratings.ATTRIBUTE_FIELDS:
        val = getattr(r, attr, None)
        d[attr] = val.value if val is not None else None
    return d


_RATING_NULL = {
    "rating": None,
    "dropped": None,
    "episodes_watched": None,
    "rating_note": None,
    "rated_at": None,
    "rating_updated_at": None,
    **{attr: None for attr in Ratings.ATTRIBUTE_FIELDS},
}


def _watchlist_columns(w: Watchlist) -> dict:
    tags = [wt.tag.name for wt in w.watchlist_tag]
    return {
        "watchlist_priority": w.priority,
        "watchlist_note": w.note,
        "watchlist_tags": tags,
        "watchlist_added_at": w.created_at.isoformat() if w.created_at else None,
    }


_WATCHLIST_NULL = {
    "watchlist_priority": None,
    "watchlist_note": None,
    "watchlist_tags": None,
    "watchlist_added_at": None,
}


async def fetch_export_data(
    db: AsyncSession, user_id: int, name_language: NameLanguage
) -> list[dict]:
    """Fetch all user data as flat media-level rows."""
    ratings_stmt = (
        select(Ratings)
        .filter_by(user_id=user_id)
        .options(selectinload(Ratings.media).selectinload(Media.anime))
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
    )
    watchlist_result = await db.execute(watchlist_stmt)
    watchlist_entries = watchlist_result.scalars().all()

    # Index by media_id for merging
    ratings_by_media: dict[int, Ratings] = {r.media_id: r for r in ratings}
    watchlist_by_media: dict[int, Watchlist] = {w.media_id: w for w in watchlist_entries}

    # Collect all media objects keyed by media_id
    all_media: dict[int, Media] = {}
    for r in ratings:
        all_media[r.media_id] = r.media
    for w in watchlist_entries:
        all_media[w.media_id] = w.media

    # Build flat rows
    rows: list[dict] = []
    for media_id, media in all_media.items():
        row = _media_columns(media, name_language)

        r = ratings_by_media.get(media_id)
        row.update(_rating_columns(r) if r else _RATING_NULL)

        w = watchlist_by_media.get(media_id)
        row.update(_watchlist_columns(w) if w else _WATCHLIST_NULL)

        rows.append(row)

    # Ensure consistent keys: include name columns only if at least one row has a value
    if name_language != NameLanguage.romaji and rows:
        for col in ("anime_name", "name"):
            has_any = any(col in row for row in rows)
            if has_any:
                for row in rows:
                    row.setdefault(col, None)

    return rows
