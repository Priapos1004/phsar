"""The galaxy map in the web process: enqueueing a rebuild, the rule that says when one is
due, and hand names. The fit itself is `galaxy_dispatcher`; the numerics are
`galaxy_compute`, run in a child process by `run_in_child`."""

import asyncio
import importlib.metadata
import logging
import multiprocessing
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_versions import make_job
from app.daos.galaxy_dao import GalaxyDAO
from app.daos.job_dao import JobDAO
from app.exceptions import GalaxyGroupNotFoundError
from app.models.galaxy import GalaxyGroup
from app.models.job import JobKind, JobStatus
from app.schemas.admin_schema import JobEnqueuedResponse
from app.services import galaxy_compute
from app.services.job_worker import job_worker
from app.services.vector_embedding_service import MODEL_NAME

logger = logging.getLogger(__name__)

galaxy_dao = GalaxyDAO()

# Every library a fit's pickle references, pinned in requirements.txt.
_PICKLED = ("umap-learn", "pynndescent", "hdbscan", "scikit-learn", "scipy", "numba", "joblib", "numpy")


async def run_in_child(fn: Callable[..., Any], *args: Any) -> Any:
    """Run one `galaxy_compute` call in a fresh process. A fit's memory peak is a large
    share of the small VM's and grows with the catalogue, and it loads numba's JIT; both
    leave with the child instead of staying in the web process, and the CPU-bound fit
    never holds the event loop's GIL. Spawn, not fork: a forked child would inherit the
    parent's threads and torch state."""
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    try:
        return await asyncio.get_running_loop().run_in_executor(pool, fn, *args)
    finally:
        pool.shutdown(wait=False)


def built_from() -> dict[str, str]:
    """What a fit depends on besides the catalogue, recorded with it: the embedding model
    its synopsis block read, and the versions of the libraries in its pickle."""
    return {"model": MODEL_NAME, **{lib: importlib.metadata.version(lib) for lib in _PICKLED}}


def refit_date(now: datetime) -> datetime:
    """The latest quarterly refit date at or before `now`: the 15th of Jan/Apr/Jul/Oct."""
    month = now.month - (now.month - 1) % 3
    date = now.replace(month=month, day=15, hour=0, minute=0, second=0, microsecond=0)
    if date > now:
        date = date.replace(year=date.year - (month == 1), month=(month - 4) % 12 + 1)
    return date


async def enqueue_rebuild(
    db: AsyncSession, *, requested_by_user_id: int | None = None, not_before_at: datetime | None = None,
) -> JobEnqueuedResponse:
    """The one enqueue path: the admin button and `ensure_map`. An admin's rebuild is
    theirs, so it shows in their bell; the system ones show in none."""
    job = make_job(
        JobKind.galaxy_rebuild, status=JobStatus.queued,
        requested_by_user_id=requested_by_user_id, not_before_at=not_before_at,
    )
    db.add(job)
    await db.commit()
    job_worker.notify()
    return JobEnqueuedResponse(job_uuid=job.uuid)


async def ensure_map(
    db: AsyncSession, *, now: datetime, not_before_at: datetime | None = None,
) -> JobEnqueuedResponse | None:
    """Enqueue a rebuild when the map is due, unless one is already waiting or the
    catalogue is too small to fit. Boot and the nightly cron both ask, so a missed night
    catches up on the next."""
    fit = await galaxy_dao.live_fit(db)
    if fit is None:
        reason = "missing"
    elif fit.params.get("built_from") != built_from():
        reason = "built from another embedding model or library versions"
    elif fit.created_at < refit_date(now):
        reason = "due its quarterly refit"
    else:
        return None
    if (
        await galaxy_dao.catalogue_size(db) < galaxy_compute.MIN_CATALOGUE
        or await JobDAO().count_active_by_kind(db, JobKind.galaxy_rebuild)
    ):
        return None
    logger.info("Galaxy map %s — rebuild enqueued", reason)
    return await enqueue_rebuild(db, not_before_at=not_before_at)


async def rename_group(db: AsyncSession, group_uuid: UUID, name: str | None) -> GalaxyGroup:
    """Set or clear a sector's or region's hand name; an empty name clears it."""
    group = await galaxy_dao.get_by_field(db, uuid=group_uuid)
    if group is None:
        raise GalaxyGroupNotFoundError(str(group_uuid))
    group.name = name or None
    await db.commit()
    return group
