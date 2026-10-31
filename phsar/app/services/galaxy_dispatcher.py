"""Dispatcher for the `galaxy_rebuild` JobKind: fit a new galaxy map in a child process
and swap it in (docs/features/galaxy.md)."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.services import galaxy_compute, galaxy_service
from app.services.galaxy_service import galaxy_dao
from app.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


async def galaxy_rebuild_dispatcher(session: AsyncSession, job: Job) -> dict[str, Any]:
    progress = ProgressReporter(job.id)
    await progress.update(stage="Loading the catalogue", force=True)
    anime, media = await galaxy_dao.load_catalogue(session)
    previous = await galaxy_dao.previous_layout(session)
    named = await galaxy_dao.named_groups(session)
    # End the read transaction before the fit rather than holding it open across it.
    await session.commit()

    await progress.update(stage="Fitting the map", force=True)
    result = await galaxy_service.run_in_child(galaxy_compute.fit, anime, media, previous)
    names = galaxy_compute.carry_names(
        named, [(g["level"], frozenset(g["trained_members"])) for g in result["groups"]],
    )
    summary = {**result["summary"], "names_carried": len(names)}

    await progress.update(stage="Saving", force=True)
    await galaxy_dao.replace_fit(
        session,
        blob=result["blob"],
        params={
            "built_from": galaxy_service.built_from(),
            "pair_cosine_percentiles": result["pair_cosine_percentiles"],
            "summary": summary,
        },
        groups=result["groups"], names=names, stars=result["stars"],
    )
    await session.commit()
    await progress.update(stage="Done", force=True)
    logger.info("Galaxy map rebuilt: %s", summary)
    return summary
