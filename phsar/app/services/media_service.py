import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_dao import MediaDAO
from app.exceptions import MalIdAlreadyExistsError
from app.models.media import Media
from app.models.media_freshness import MediaFreshness
from app.models.media_relation_edges import MediaRelationEdges
from app.schemas.media_schema import MediaUnconnected
from app.services.media_linking_service import (
    link_genres_to_media,
    link_studios_to_media,
)
from app.services.vector_embedding_service import create_media_embedding

logger = logging.getLogger(__name__)

media_dao = MediaDAO()

async def create_media(db: AsyncSession, media_in: MediaUnconnected, anime_id: int) -> Media:
    logger.debug(f"DB session: {id(db)}")
    # Check if media already exists in the database
    existing = await media_dao.get_by_mal_id(db, media_in.mal_id)
    if existing:
        raise MalIdAlreadyExistsError(media_in.mal_id, media_in.title)

    media_obj = Media(
        **media_in.model_dump(exclude={"genres", "studio"}),
        anime_id=anime_id
    )
    await media_dao.create(db, media_obj)
    return media_obj


def media_unconnected_from_info(media_info: dict, relation_type: str) -> MediaUnconnected:
    """Build a MediaUnconnected from a JikanScraper.extract_information dict.
    Used by both user_scrape (search_service) and the sweep probe
    (save_service.attach_search_result_to_anime) so both paths share
    identical schema-construction defaults."""
    return MediaUnconnected(
        mal_id=media_info["mal_id"],
        mal_url=media_info.get("mal_url"),
        title=media_info.get("title"),
        name_eng=media_info.get("name_eng"),
        name_jap=media_info.get("name_jap"),
        other_names=media_info.get("other_names"),
        media_type=media_info.get("media_type"),
        relation_type=relation_type,
        age_rating=media_info.get("age_rating"),
        description=media_info.get("description"),
        original_source=media_info.get("original_source"),
        cover_image=media_info.get("cover_image"),
        score=media_info.get("score"),
        scored_by=media_info.get("scored_by"),
        episodes=media_info.get("episodes"),
        anime_season_name=media_info.get("anime_season_name"),
        anime_season_year=media_info.get("anime_season_year"),
        airing_status=media_info.get("airing_status"),
        aired_from=media_info.get("aired_from"),
        aired_to=media_info.get("aired_to"),
        duration=media_info.get("duration"),
        duration_seconds=media_info.get("duration_seconds"),
        genres=media_info.get("genres"),
        studio=media_info.get("studio"),
    )


async def persist_media_with_links(
    db: AsyncSession,
    media_in: MediaUnconnected,
    anime_id: int,
    last_checked_at: datetime | None,
    relation_edges: list[tuple[int, str]] | None = None,
) -> Media:
    """Create one Media + its sidecars + genre/studio links + embedding.
    Single source of truth for the per-media insert path so user_scrape
    and the sweep probe can't drift on schema additions. `last_checked_at`
    is None for never-fetched rows (user_scrape on a fresh anime) and
    `now()` for sweep-probe-discovered rows where MAL data is fresh.
    `relation_edges` is the per-media outgoing MAL relations captured by
    BFS — `[(target_mal_id, normalized_rel), ...]`; defaults to empty
    so the backfiller can later populate via lazy MAL fetch."""
    media_obj = await create_media(db, media_in, anime_id=anime_id)
    media_obj.freshness = MediaFreshness(last_checked_at=last_checked_at)
    # Normalize tuples to lists so the in-memory cached attribute
    # matches the JSONB round-trip shape (asyncpg returns arrays as
    # lists). Without this, callers reading from the session identity
    # map see tuples while a fresh SELECT sees lists.
    #
    # `last_fetched_at` stamped only when the caller passed BFS-captured
    # edges (relation_edges is not None) — those came from MAL during
    # the scrape, so they count as a confirmed sync even when the list
    # is empty. If a future caller omits relation_edges entirely, the
    # sidecar stays None-stamped so the lifespan backfiller picks it up.
    last_fetched_at = (
        datetime.now(timezone.utc) if relation_edges is not None else None
    )
    media_obj.relation_edges = MediaRelationEdges(
        edges=[list(edge) for edge in (relation_edges or [])],
        last_fetched_at=last_fetched_at,
    )
    await link_genres_to_media(db, media_id=media_obj.id, genres=media_in.genres)
    await link_studios_to_media(db, media_id=media_obj.id, studios=media_in.studio)
    await create_media_embedding(
        db,
        media_id=media_obj.id,
        title_texts=[
            media_in.title,
            media_in.name_eng,
            media_in.name_jap,
            *media_in.other_names,
        ],
        description_text=media_in.description,
    )
    return media_obj
