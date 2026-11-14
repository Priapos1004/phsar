"""Dispatcher for the `recommender_eval` JobKind: measure the recommender in a child process and
apply its refit unless a guard holds it back (docs/features/recommender.md, "The weekly job")."""

import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.job_dao import JobDAO
from app.daos.watch_event_dao import WatchEventDAO
from app.models.job import Job, JobKind
from app.services import child_process, recommender_eval, recommender_service
from app.services.progress_reporter import ProgressReporter
from app.services.recommender_service import recommendation_dao

logger = logging.getLogger(__name__)


async def recommender_eval_dispatcher(session: AsyncSession, job: Job) -> dict[str, Any]:
    progress = ProgressReporter(job.id)
    await progress.update(stage="Loading the histories", force=True)
    cat = await recommender_service.load_catalogue(session)
    listed_from = await recommender_service.load_log_start(session)
    # Plain tuples, so the child unpickles them without importing the app.
    histories = {u: (h.ratings, h.listings, h.franchise) for u, h in (await recommender_service.load_histories(session)).items()}
    watches = await WatchEventDAO().by_user(session)
    exposure = await recommendation_dao.exposure(session)
    fit, live = await recommender_service.live_weights(session)
    previous = await JobDAO().latest_summaries(session, JobKind.recommender_eval, recommender_eval.HELP_RUNS - 1)
    # End the read transaction before the measuring rather than holding it open across it.
    await session.commit()

    await progress.update(stage="Measuring", force=True)
    summary = await child_process.run_in_child(
        recommender_eval.weekly, cat, histories, listed_from, watches, exposure, live, previous, time.time(),
    )
    refit = summary["report"]["weights"]["refit"]
    if summary["verdict"] == "applied" and refit != live:
        fit = (await recommendation_dao.add_fit(session, refit)).uuid
        await session.commit()
    summary["fit"] = str(fit) if fit is not None else None
    await progress.update(stage="Done", force=True)
    logger.info("Recommender eval: %s, log %s", summary["verdict"], summary["log"])
    return summary
