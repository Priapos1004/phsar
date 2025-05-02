import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_dao import MediaDAO
from app.daos.media_unwanted_dao import MediaUnwantedDAO
from app.exceptions import MainMediaNotFoundError
from app.schemas.media_schema import MediaUnconnected
from app.schemas.search_schema import SearchResultDB, SearchResultDBExtended
from app.services.jikan_scraper import JikanScraper
from app.services.unwanted_media_service import create_unwanted_media

logger = logging.getLogger(__name__)
media_dao = MediaDAO()
media_unwanted_dao = MediaUnwantedDAO()

def get_first_main_relation(media_dict: dict[int, dict]) -> int:
    for mal_id, media in media_dict.items():
        if media.get("relation_type") == "main":
            return mal_id

    title_relation_tuple = [(media.get("title"), media.get("relation_type")) for media in media_dict.values()]
    raise MainMediaNotFoundError(title_relation_tuple)  # If no main relation found

async def search_mal_api(query: str, excluded_mal_ids: set[int]) -> SearchResultDBExtended:
    async with JikanScraper() as scraper:
        relations, all_info, unwanted_media = await scraper.search_title(query, excluded_mal_ids=excluded_mal_ids)

    result_list = []
    for related_anime_graph in relations:

        anime_mal_id = get_first_main_relation(related_anime_graph)

        unconnected_media_list = []
        for mal_id, relation_info in related_anime_graph.items():
            media_info = all_info[mal_id]
            media = MediaUnconnected(
                mal_id=mal_id,
                mal_url=media_info.get("mal_url"),
                title=media_info.get("title"),
                name_eng=media_info.get("name_eng"),
                name_jap=media_info.get("name_jap"),
                other_names=media_info.get("other_names"),
                media_type=media_info.get("media_type"),
                relation_type=relation_info.get("relation_type"),
                fsk=media_info.get("fsk"),
                description=media_info.get("description"),
                original_source=media_info.get("original_source"),
                cover_image=media_info.get("cover_image"),
                score=media_info.get("score"),
                scored_by=media_info.get("scored_by"),
                episodes=media_info.get("episodes"),
                anime_season=media_info.get("anime_season"),
                airing_status=media_info.get("airing_status"),
                aired_from=media_info.get("aired_from"),
                aired_to=media_info.get("aired_to"),
                duration=media_info.get("duration"),
                genres=media_info.get("genres"),
                studio=media_info.get("studio"),
            )
            # Put the main anime always at the beginning of the list
            if mal_id == anime_mal_id:
                unconnected_media_list = [media] + unconnected_media_list
            else:
                unconnected_media_list.append(media)

        result_list.append(SearchResultDB(anime_mal_id=anime_mal_id, unconnected_media_list=unconnected_media_list))
    
    return SearchResultDBExtended(search_result_db_list=result_list, unwanted_media=unwanted_media)

async def handle_search_mal_api_results(
    db: AsyncSession,
    query: str,
) -> list[SearchResultDB]:
    existing_mal_ids = set(await media_dao.get_all_mal_ids(db))
    unwanted_ids = set(await media_unwanted_dao.get_all_mal_ids(db))
    all_excluded_ids = existing_mal_ids | unwanted_ids
    result = await search_mal_api(query, excluded_mal_ids=all_excluded_ids)

    if result.unwanted_media:
        try:
            await create_unwanted_media(db, result.unwanted_media)
        except Exception as e:
            logger.error(f"Failed to save unwanted media: {e}")

    logger.info(f"/search/mal query='{query}' returned {len(result.search_result_db_list)} results, {len(result.unwanted_media)} unwanted media.")
    
    return result.search_result_db_list
