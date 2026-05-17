import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_dao import MediaDAO
from app.daos.media_unwanted_dao import MediaUnwantedDAO
from app.exceptions import MainMediaNotFoundError
from app.schemas.search_schema import (
    AttachToExistingAction,
    SearchResultDB,
    SearchResultDBExtended,
)
from app.services.jikan_scraper import JikanScraper
from app.services.media_service import media_unconnected_from_info
from app.services.progress_reporter import ProgressReporter
from app.services.relation_classifier import (
    build_classifier_nodes,
    classify_anime_relations,
    passes_substance,
)
from app.services.unwanted_media_service import create_unwanted_media

logger = logging.getLogger(__name__)
media_dao = MediaDAO()
media_unwanted_dao = MediaUnwantedDAO()


def get_first_main_relation(media_dict: dict[int, dict]) -> int:
    for mal_id, media in media_dict.items():
        if media.get("relation_type") == "main":
            return mal_id

    title_relation_tuple = [(media.get("title", ""), media.get("relation_type", "")) for media in media_dict.values()]
    raise MainMediaNotFoundError(title_relation_tuple)


async def search_mal_api(
    query: str | None,
    excluded_mal_ids: set[int],
    progress: ProgressReporter | None = None,
    seed_mal_id: int | None = None,
    unwanted_mal_ids: set[int] | None = None,
) -> SearchResultDBExtended:
    # seed_mal_id bypasses the fuzzy q= lookup so callers with a known
    # mal_id (seasonal sweep, future admin tools) don't pull unrelated
    # top-3 matches into the catalog.
    # `unwanted_mal_ids` is the subset of `excluded_mal_ids` that lives
    # in MediaUnwanted (Music/PV/CM/Hentai) rather than the regular
    # catalog. We pass it separately so the BFS still skips them
    # (excluded_mal_ids) but the cross_link / attach-action logic below
    # doesn't treat them as franchise overlaps — they're filtered media,
    # not part of any anime, and trying to attach to them resolves to no
    # parent.
    unwanted_mal_ids = unwanted_mal_ids or set()
    async with JikanScraper() as scraper:
        relations, all_info, unwanted_media = await scraper.search_title(
            title=query,
            excluded_mal_ids=excluded_mal_ids,
            progress=progress,
            seed_mal_id=seed_mal_id,
        )

    result_list: list[SearchResultDB] = []
    attach_actions: list[AttachToExistingAction] = []
    for related_anime_graph, edges, cross_link_mal_ids in relations:
        # MediaUnwanted entries reached via cross-link are filtered
        # media, not franchise overlaps — strip them so the attach
        # fallback below doesn't resolve to a parent that doesn't exist.
        cross_link_mal_ids = cross_link_mal_ids - unwanted_mal_ids

        nodes = build_classifier_nodes(related_anime_graph, all_info)
        classifications, anime_mal_id = classify_anime_relations(nodes, edges)
        for mal_id, relation_type in classifications.items():
            related_anime_graph[mal_id]["relation_type"] = relation_type

        # Substance-failing anchor means the graph's "main" is a weak
        # fallback (donghua with sparse metadata, orphan side-story).
        # Three-way decision:
        #   (1) Single cross-link to an existing parent → attach instead
        #       of creating a duplicate anime row.
        #   (2) Seeded BFS mode → save as new anime; the seasonal sweep
        #       picked this mal_id deliberately.
        #   (3) Title-search mode with no cross-link → fuzzy-match
        #       garbage, skip.
        if not passes_substance(nodes[anime_mal_id]):
            if len(cross_link_mal_ids) == 1:
                target_mal_id = next(iter(cross_link_mal_ids))
                graph_all_info = {
                    mid: all_info[mid] for mid in related_anime_graph if mid in all_info
                }
                attach_actions.append(AttachToExistingAction(
                    target_mal_id=target_mal_id,
                    related_anime_graph=related_anime_graph,
                    all_info=graph_all_info,
                    edges=edges,
                ))
                logger.info(
                    "Weak-anchor graph will attach to mal_id=%s (anchor=%s)",
                    target_mal_id, anime_mal_id,
                )
                continue
            if seed_mal_id is None:
                logger.warning(
                    "Skipping weak-anchor graph (cross_links=%s, anchor=%s)",
                    cross_link_mal_ids, anime_mal_id,
                )
                continue
            # Seeded mode: log the weak-anchor save and fall through to
            # the unconnected_media_list build below.
            logger.info(
                "Seeded weak-anchor graph saving as new anime "
                "(seed=%s, anchor=%s, type=%s)",
                seed_mal_id, anime_mal_id,
                related_anime_graph[anime_mal_id].get("media_type"),
            )

        unconnected_media_list = []
        for mal_id, relation_info in related_anime_graph.items():
            media = media_unconnected_from_info(
                all_info[mal_id], relation_type=relation_info["relation_type"],
            )
            if mal_id == anime_mal_id:
                unconnected_media_list = [media] + unconnected_media_list
            else:
                unconnected_media_list.append(media)

        result_list.append(SearchResultDB(
            anime_mal_id=anime_mal_id,
            unconnected_media_list=unconnected_media_list,
            cross_link_mal_ids=cross_link_mal_ids,
            edges=edges,
        ))

    return SearchResultDBExtended(
        search_result_db_list=result_list,
        unwanted_media=unwanted_media,
        attach_actions=attach_actions,
    )

async def handle_search_mal_api_results(
    db: AsyncSession,
    query: str | None,
    progress: ProgressReporter | None = None,
    seed_mal_id: int | None = None,
) -> SearchResultDBExtended:
    """Run a MAL search/BFS, persist the unwanted_media side-table, and
    return the full extended result so callers can route attach_actions
    in addition to the regular search_result_db_list.

    Return type changed from `list[SearchResultDB]` to the extended
    object so the dispatcher path can attach orphan-side-story graphs to
    existing parents (the new auto-attach behavior). Non-dispatcher
    callers (`/search/mal` route, media seeder) just unwrap
    `.search_result_db_list` and stay on the legacy path.
    """
    existing_mal_ids = set(await media_dao.get_all_mal_ids(db))
    unwanted_ids = set(await media_unwanted_dao.get_all_mal_ids(db))
    all_excluded_ids = existing_mal_ids | unwanted_ids
    result = await search_mal_api(
        query,
        excluded_mal_ids=all_excluded_ids,
        progress=progress,
        seed_mal_id=seed_mal_id,
        unwanted_mal_ids=unwanted_ids,
    )

    if result.unwanted_media:
        try:
            await create_unwanted_media(db, result.unwanted_media)
        except Exception:
            logger.exception("Failed to save unwanted media")

    logger.info(
        "/search/mal query=%r returned %d results, %d unwanted media, %d attach actions.",
        query,
        len(result.search_result_db_list),
        len(result.unwanted_media),
        len(result.attach_actions),
    )
    await db.commit()  # Single commit at the end!

    return result
