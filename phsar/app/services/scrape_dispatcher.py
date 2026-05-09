"""Dispatchers that run inside the JobWorker.

The user_scrape dispatcher fetches the chosen anime + its relations from MAL
and persists them. Progress updates come from a ProgressReporter that opens
its own short-lived session per write, so the navbar bell can poll progress
without waiting for the dispatcher's main transaction to commit.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AnimeNotFoundError
from app.models.job import Job
from app.services.progress_reporter import ProgressReporter
from app.services.save_service import save_search_results
from app.services.search_service import handle_search_mal_api_results

logger = logging.getLogger(__name__)


async def user_scrape_dispatcher(session: AsyncSession, job: Job) -> dict:
    """BFS everything matching the query and save all results.

    payload: {"query": str}. The 3-candidate search is for query imprecision,
    not user choice — connected candidates dedupe through the shared visited
    set in search_title; unconnected ones each become their own anime row.
    """
    payload = job.payload or {}
    query = payload.get("query")
    if not query:
        raise ValueError(f"user_scrape payload must include query, got {payload!r}")

    progress = ProgressReporter(job.id)

    await progress.update(stage="Fetching", force=True)
    results = await handle_search_mal_api_results(db=session, query=query, progress=progress)
    # search_title raises AnimeNotFoundError when MAL returns zero hits, but
    # if every hit was filtered as Music/PV/CM/Hentai it returns successfully
    # with an empty list — caller still has nothing to save.
    if not results:
        raise AnimeNotFoundError(query)

    media_count = sum(len(r.unconnected_media_list) for r in results)
    await progress.update(stage="Saving", items_total=media_count, items_done=0, force=True)
    await save_search_results(session, results, progress=progress)
    # "Done" while the row is still status='running' is brief — the worker
    # flips to succeeded immediately after this dispatcher returns. Showing
    # it gives the user a clean terminal label instead of a stuck "Saving".
    await progress.update(stage="Done", items_done=media_count, force=True)

    return {
        "anime_count": len(results),
        "media_count": media_count,
    }
