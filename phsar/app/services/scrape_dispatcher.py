"""Dispatchers that run inside the JobWorker.

The user_scrape dispatcher fetches the chosen anime + its relations from MAL
and persists them. Progress updates go to the job row in their own short
session so the navbar bell can poll progress without waiting for the
dispatcher's main transaction to commit.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.daos.job_dao import JobDAO
from app.exceptions import AnimeNotFoundError
from app.models.job import Job
from app.services.save_service import save_search_results
from app.services.search_service import handle_search_mal_api_results

logger = logging.getLogger(__name__)
job_dao = JobDAO()


class ProgressReporter:
    """Writes job progress in a fresh short-lived session so the frontend
    sees updates without waiting for the dispatcher's main tx to commit."""

    def __init__(self, job_id: int):
        self._job_id = job_id

    async def update(
        self,
        stage: str | None = None,
        items_done: int | None = None,
        items_total: int | None = None,
    ) -> None:
        async with async_session_maker() as session:
            job = await job_dao.get_by_id(session, self._job_id)
            if job is None:
                logger.debug("Progress update for missing job %s — ignored", self._job_id)
                return
            await job_dao.mark_progress(
                session, job, stage=stage, items_done=items_done, items_total=items_total,
            )
            await session.commit()


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

    await progress.update(stage="fetching")
    results = await handle_search_mal_api_results(db=session, query=query)
    # search_title raises AnimeNotFoundError when MAL returns zero hits, but
    # if every hit was filtered as Music/PV/CM/Hentai it returns successfully
    # with an empty list — caller still has nothing to save.
    if not results:
        raise AnimeNotFoundError(query)

    media_count = sum(len(r.unconnected_media_list) for r in results)
    await progress.update(stage="saving", items_total=media_count, items_done=0)
    await save_search_results(session, results)
    await progress.update(items_done=media_count)

    return {
        "anime_count": len(results),
        "media_count": media_count,
    }
