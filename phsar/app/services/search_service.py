import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_dao import MediaDAO
from app.daos.media_unwanted_dao import MediaUnwantedDAO
from app.exceptions import MainMediaNotFoundError
from app.schemas.search_schema import SearchResultDB, SearchResultDBExtended
from app.services.jikan_scraper import JikanScraper
from app.services.media_service import media_unconnected_from_info
from app.services.progress_reporter import ProgressReporter
from app.services.unwanted_media_service import create_unwanted_media

logger = logging.getLogger(__name__)
media_dao = MediaDAO()
media_unwanted_dao = MediaUnwantedDAO()

def get_first_main_relation(media_dict: dict[int, dict]) -> int:
    for mal_id, media in media_dict.items():
        if media.get("relation_type") == "main":
            return mal_id

    title_relation_tuple = [(media.get("title", ""), media.get("relation_type", "")) for media in media_dict.values()]
    raise MainMediaNotFoundError(title_relation_tuple)  # If no main relation found

async def search_mal_api(
    query: str,
    excluded_mal_ids: set[int],
    progress: ProgressReporter | None = None,
) -> SearchResultDBExtended:
    async with JikanScraper() as scraper:
        relations, all_info, unwanted_media = await scraper.search_title(
            query, excluded_mal_ids=excluded_mal_ids, progress=progress,
        )

    result_list = []
    for related_anime_graph, cross_link_mal_ids in relations:
        # MAL returns long-tail garbage for short or vague queries. A graph
        # without a clear main story is unsavable as a standalone anime, so
        # skip it instead of failing the entire scrape — other graphs from
        # the same query may still be valid (e.g. one good main + one weird).
        try:
            anime_mal_id = get_first_main_relation(related_anime_graph)
        except MainMediaNotFoundError as exc:
            logger.warning(
                "Skipping graph without main story: %s",
                exc.title_relation_tuple,
            )
            continue

        unconnected_media_list = []
        for mal_id, relation_info in related_anime_graph.items():
            media = media_unconnected_from_info(
                all_info[mal_id], relation_type=relation_info.get("relation_type"),
            )
            # Put the main anime always at the beginning of the list
            if mal_id == anime_mal_id:
                unconnected_media_list = [media] + unconnected_media_list
            else:
                unconnected_media_list.append(media)

        result_list.append(SearchResultDB(
            anime_mal_id=anime_mal_id,
            unconnected_media_list=unconnected_media_list,
            cross_link_mal_ids=cross_link_mal_ids,
        ))
    
    return SearchResultDBExtended(search_result_db_list=result_list, unwanted_media=unwanted_media)

async def handle_search_mal_api_results(
    db: AsyncSession,
    query: str,
    progress: ProgressReporter | None = None,
) -> list[SearchResultDB]:
    existing_mal_ids = set(await media_dao.get_all_mal_ids(db))
    unwanted_ids = set(await media_unwanted_dao.get_all_mal_ids(db))
    all_excluded_ids = existing_mal_ids | unwanted_ids
    result = await search_mal_api(query, excluded_mal_ids=all_excluded_ids, progress=progress)

    if result.unwanted_media:
        try:
            await create_unwanted_media(db, result.unwanted_media)
        except Exception:
            logger.exception("Failed to save unwanted media")

    logger.info(f"/search/mal query='{query}' returned {len(result.search_result_db_list)} results, {len(result.unwanted_media)} unwanted media.")
    await db.commit()  # Single commit at the end!
    
    return result.search_result_db_list
