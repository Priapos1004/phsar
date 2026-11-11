"""Dispatcher for the `galaxy_rebuild` JobKind: fit a new galaxy map in a child process
and swap it in (docs/features/galaxy.md)."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import GalaxyVectorsStaleError
from app.models.job import Job
from app.seeders.embedding_backfiller import embeddings_are_stale
from app.services import galaxy_compute, galaxy_service
from app.services.galaxy_service import galaxy_dao
from app.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


async def galaxy_rebuild_dispatcher(session: AsyncSession, job: Job) -> dict[str, Any]:
    progress = ProgressReporter(job.id)
    # The worker runs beside a re-embed (`sync_vectors_and_map`): a fit now would read a mix of
    # two models' vectors.
    if await embeddings_are_stale(session):
        raise GalaxyVectorsStaleError()
    await progress.update(stage="Loading the catalogue", force=True)
    anime, media = await galaxy_dao.load_catalogue(session)
    # Cold after the vectors change (docs/features/galaxy.md, "A refit starts from the live
    # map"); names carry either way, by members.
    fit = await galaxy_dao.live_fit(session)
    previous = await galaxy_dao.previous_layout(session) if galaxy_service.same_vectors(fit) else {}
    # End the read transaction before the fit rather than holding it open across it.
    await session.commit()

    await progress.update(stage="Fitting the map", force=True)
    result = await galaxy_service.run_in_child(galaxy_compute.fit, anime, media, previous)
    # Read after the fit, so a rename made while it ran carries too.
    named = await galaxy_dao.named_groups(session)
    groups = result["groups"]
    names, dropped = galaxy_compute.carry_names(
        named, [(g["level"], frozenset(g["trained_members"])) for g in groups],
    )
    # Each group the members went to by its number, which a label ("mixed") is not unique
    # enough to stand in for, and by the label the map shows (`GalaxyDAO.map_groups`).
    names_dropped = [
        {"name": name, "level": level,
         "went_to": [{"number": groups[j]["number"], "label": names.get(j) or groups[j]["auto_name"],
                      "share": round(share, 2)} for j, share in went]}
        for level, name, went in dropped
    ]
    # The fit keeps the summary without the list: `live_fit` loads it on every map and
    # neighbours request, and the list is only the job's to report.
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
        groups=groups, names=names, stars=result["stars"],
    )
    await session.commit()
    await progress.update(stage="Done", force=True)
    logger.info("Galaxy map rebuilt: %s", summary)
    return {**summary, "names_dropped": names_dropped}
