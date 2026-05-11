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


# Type-tier preference for the main-promotion fallback (Option B).
# Lower number = more "main-like". TV/Movie are the canonical mains;
# ONA covers donghua and modern web-original Japanese series (the
# whole reason this fallback exists); OVA / TV Special are usually
# auxiliary releases; Special is mostly recap/pilot material that
# shouldn't out-rank a real series. Anything missing scores 99 so it
# never beats a typed entry.
_MAIN_PROMOTION_TYPE_TIER = {
    "tv": 0,
    "movie": 0,
    "ona": 1,
    "ova": 2,
    "tv special": 2,
    "tvspecial": 2,
    "special": 3,
}


def _pick_root_for_promotion(graph: dict[int, dict]) -> int | None:
    """When `get_first_main_relation` fails AND we're in seeded BFS mode
    (a seasonal-sweep child for a specific mal_id), pick the entry to
    promote to `main` instead of giving up. Sort by
    `(type_tier, aired_from)` so TV/Movie beats ONA beats Special even
    when a Special aired earlier — handles the
    pilot-aired-before-the-real-show edge. nulls-last on aired_from."""
    if not graph:
        return None

    def sort_key(item):
        _mal_id, info = item
        media_type = (info.get("media_type") or "").lower()
        tier = _MAIN_PROMOTION_TYPE_TIER.get(media_type, 99)
        aired = info.get("aired_from")
        # `aired is None` puts nulls AFTER non-nulls within the same tier.
        return (tier, aired is None, aired or "")

    return sorted(graph.items(), key=sort_key)[0][0]

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
    for related_anime_graph, cross_link_mal_ids in relations:
        # Filter cross_link signals: MediaUnwanted entries that the BFS
        # reached via an existing-in-catalog hit are filtered media, not
        # franchise overlaps. Without this filter, a graph that only
        # cross-links to a Music/PV/CM entry would falsely qualify for
        # the attach-action fallback below, then fail when the
        # dispatcher tries to resolve the target mal_id to a parent
        # Anime (MediaUnwanted has no Anime FK). Merge-detection also
        # benefits — `resolve_cross_link_pairs` already silently drops
        # these, but filtering here keeps the signal honest end-to-end.
        cross_link_mal_ids = cross_link_mal_ids - unwanted_mal_ids
        # Three-tier fallback for graphs that fail `get_first_main_relation`:
        #   (1) single cross-link to an existing catalog anime → attach action
        #       (typical for seasonal-sweep children that are side-stories of
        #       shows we already have)
        #   (2) seeded BFS mode (we know the target mal_id, no anchor in
        #       catalog) → promote the most main-like entry of the orphan
        #       sub-graph and save as a NEW anime. This is what onboards
        #       brand-new donghua franchises whose canonical 'main' is an
        #       ONA (which doesn't match the BFS's TV/Movie is_main_story
        #       gate). Promoted entry is chosen by
        #       `_pick_root_for_promotion` (type tier > aired_from).
        #   (3) title-search mode (no seed_mal_id) with no anchor → skip;
        #       the search hit was likely fuzzy-match garbage.
        try:
            anime_mal_id = get_first_main_relation(related_anime_graph)
        except MainMediaNotFoundError as exc:
            # Fallback (1): single cross-link → attach to existing parent.
            if len(cross_link_mal_ids) == 1:
                target_mal_id = next(iter(cross_link_mal_ids))
                graph_all_info = {
                    mid: all_info[mid] for mid in related_anime_graph if mid in all_info
                }
                attach_actions.append(AttachToExistingAction(
                    target_mal_id=target_mal_id,
                    related_anime_graph=related_anime_graph,
                    all_info=graph_all_info,
                ))
                logger.info(
                    "Graph without main story will attach to mal_id=%s: %s",
                    target_mal_id, exc.title_relation_tuple,
                )
                continue
            # Fallback (2): seeded mode with no anchor → promote a root.
            if seed_mal_id is not None:
                root_mal_id = _pick_root_for_promotion(related_anime_graph)
                if root_mal_id is None:
                    logger.warning(
                        "Seeded BFS for mal_id=%s produced an empty graph; skipping.",
                        seed_mal_id,
                    )
                    continue
                related_anime_graph[root_mal_id]["relation_type"] = "main"
                anime_mal_id = root_mal_id
                logger.warning(
                    "Seeded BFS for mal_id=%s had no main; promoted mal_id=%s "
                    "(type=%s, aired=%s) to main and saving as new Anime.",
                    seed_mal_id, root_mal_id,
                    related_anime_graph[root_mal_id].get("media_type"),
                    related_anime_graph[root_mal_id].get("aired_from"),
                )
                # Fall through to the regular save path below using
                # `anime_mal_id`. (NOTE: deliberately no `continue` here.)
            else:
                # Fallback (3): title-search with no anchor → skip.
                logger.warning(
                    "Skipping graph without main story (cross_links=%s): %s",
                    cross_link_mal_ids, exc.title_relation_tuple,
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
