"""The galaxy map in the web process: serving it, placing new anime onto it, enqueueing a
rebuild and the rule that says when one is due, and hand names. The fit itself is `galaxy_dispatcher`; the
numerics are `galaxy_compute`, run in a child process by `run_in_child`."""

import asyncio
import importlib.metadata
import logging
import multiprocessing
from bisect import bisect_right
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_versions import make_job
from app.core.maintenance import restores
from app.daos.galaxy_dao import GalaxyDAO
from app.daos.job_dao import JobDAO
from app.exceptions import (
    ConfirmationMismatchError,
    GalaxyGroupNotFoundError,
    GalaxyRestoredError,
    GalaxyStarNotFoundError,
)
from app.models.galaxy import GalaxyGroup
from app.models.job import JobKind, JobStatus
from app.schemas.admin_schema import JobEnqueuedResponse
from app.schemas.galaxy_schema import (
    GalaxyMapOut,
    GalaxyNeighbourOut,
    GalaxyRegionOut,
    GalaxySectorOut,
    GalaxySharedOut,
    GalaxyStarOut,
)
from app.services import galaxy_compute
from app.services.job_worker import job_worker
from app.services.vector_embedding_service import MODEL_NAME, cosine_similarity

logger = logging.getLogger(__name__)

galaxy_dao = GalaxyDAO()

# How many nearest stars a pinned anime shows.
NEIGHBOURS = 8
# What a neighbour shares, ranked by how rarely two anime share it by chance: the rarest
# few, and nothing one random pair in four already shares, which says little.
SHARED_SHOWN = 5
SHARED_CHANCE_MAX = 0.25

# Every library a fit's pickle references, pinned in requirements.txt.
_PICKLED = ("umap-learn", "pynndescent", "hdbscan", "scikit-learn", "scipy", "numba", "joblib", "numpy")


async def run_in_child(fn: Callable[..., Any], *args: Any) -> Any:
    """Run one `galaxy_compute` call in a fresh process. A fit's memory peak is a large
    share of the small VM's and grows with the catalogue, and it loads numba's JIT; both
    leave with the child instead of staying in the web process, and the CPU-bound fit
    never holds the event loop's GIL. Spawn, not fork: a forked child would inherit the
    parent's threads and torch state.

    A restore while the child runs discards its answer (`maintenance.restores` says why)."""
    restores_before = restores()
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    try:
        result = await asyncio.get_running_loop().run_in_executor(pool, fn, *args)
    finally:
        pool.shutdown(wait=False)
    if restores() != restores_before:
        raise GalaxyRestoredError()
    return result


def built_from() -> dict[str, str]:
    """What a fit depends on besides the catalogue, recorded with it."""
    return {
        "model": MODEL_NAME, "vectors": galaxy_compute.vectors_key(), "fitting": str(galaxy_compute.FITTING),
        **{lib: importlib.metadata.version(lib) for lib in _PICKLED},
    }


def is_current(fit: Any) -> bool:
    """Built from what the code builds from now, so its pickle still places new stars."""
    return fit.params.get("built_from") == built_from()


def same_vectors(fit: Any) -> bool:
    """Its stars' vectors are the ones a refit would build (same model and `vectors_key`), so a
    refit can start from its layout."""
    then, now = (fit.params.get("built_from") or {}) if fit is not None else {}, built_from()
    return fit is not None and all(then.get(k) == now[k] for k in ("model", "vectors"))


def refit_date(now: datetime) -> datetime:
    """The latest quarterly refit date at or before `now`: the 15th of Jan/Apr/Jul/Oct."""
    month = now.month - (now.month - 1) % 3
    date = now.replace(month=month, day=15, hour=0, minute=0, second=0, microsecond=0)
    if date > now:
        date = date.replace(year=date.year - (month == 1), month=(month - 4) % 12 + 1)
    return date


async def vectors_reembedded(db: AsyncSession) -> None:
    """The stored synopsis vectors were re-encoded under the live map, which `built_from`
    cannot see when the model name stayed: mark its vectors stale, so the map is refit, from
    no layout, and takes no new stars meanwhile."""
    fit = await galaxy_dao.live_fit(db)
    if fit is not None:
        fit.params = {**fit.params, "built_from": {**fit.params.get("built_from", {}), "vectors": "re-embedded"}}
        await db.commit()


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


async def rebuild_for_admin(db: AsyncSession, *, confirm: str, username: str, user_id: int) -> JobEnqueuedResponse:
    """An admin's rebuild, gated on their username; `ensure_map` enqueues past this check."""
    if confirm != username:
        raise ConfirmationMismatchError()
    return await enqueue_rebuild(db, requested_by_user_id=user_id)


async def ensure_map(
    db: AsyncSession, *, now: datetime, not_before_at: datetime | None = None,
) -> JobEnqueuedResponse | None:
    """Enqueue a rebuild when the map is due, unless one is already waiting or the
    catalogue is too small to fit. Asked whenever the map may be due (docs/features/galaxy.md,
    "When the map is rebuilt"), so a missed night catches up on the next."""
    fit = await galaxy_dao.live_fit(db)
    if fit is None:
        reason = "missing"
    elif not is_current(fit):
        reason = "built from something that has changed"
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


async def get_map(db: AsyncSession) -> GalaxyMapOut:
    fit = await galaxy_dao.live_fit(db)
    if fit is None:
        return GalaxyMapOut(fitted_at=None, sectors=[], regions=[], stars=[])
    groups = await galaxy_dao.map_groups(db)
    return GalaxyMapOut(
        fitted_at=fit.created_at,
        sectors=[GalaxySectorOut(**g._mapping) for g in groups if g.sector is None],
        regions=[GalaxyRegionOut(**g._mapping) for g in groups if g.sector is not None],
        stars=[GalaxyStarOut(**{**s._mapping, "genres": s.genres or []}) for s in await galaxy_dao.map_stars(db)],
    )


async def neighbours(db: AsyncSession, anime_uuid: UUID) -> list[GalaxyNeighbourOut]:
    """The `NEIGHBOURS` nearest stars (`GalaxyDAO.nearest`), nearest first, each with what it
    shares with this one."""
    star = await galaxy_dao.star_features(db, anime_uuid)
    if star is None:
        raise GalaxyStarNotFoundError(str(anime_uuid))
    near = await galaxy_dao.nearest(db, star.anime_id, star.features, NEIGHBOURS)
    facts = await galaxy_dao.anime_facts(db, [star.anime_id, *near])
    fit = await galaxy_dao.live_fit(db)
    assert fit is not None  # a star belongs to the live fit
    percentiles = fit.params["pair_cosine_percentiles"]
    total, counts = await galaxy_dao.trait_counts(db)
    me = facts[star.anime_id]

    def traits(kind: Literal["genre", "studio", "source", "format"], mine: list[str], theirs: list[str]) -> list[GalaxySharedOut]:
        return [GalaxySharedOut(kind=kind, name=n, chance=counts.get((kind, n), 0) / total) for n in set(mine) & set(theirs)]

    def synopsis(me: Row, other: Row) -> list[GalaxySharedOut]:
        """How alike two synopses read, against random pairs; none when either has none, its
        embedding then reading the titles alone."""
        if not (me.has_synopsis and other.has_synopsis):
            return []
        similarity = cosine_similarity(me.description_embedding, other.description_embedding)
        percentile = max(0, bisect_right(percentiles, similarity) - 1)
        return [GalaxySharedOut(kind="synopsis", name=None, chance=(100 - percentile) / 100)]

    def one(value: Any) -> list[str]:
        """A single-valued trait as the none-or-one list `traits` intersects, like the list-valued ones."""
        return [value.value] if value is not None else []

    out = []
    for anime_id in near:
        other = facts[anime_id]
        shared = [
            *synopsis(me, other),
            *traits("genre", me.genres or [], other.genres or []),
            *traits("studio", me.studios or [], other.studios or []),
            *traits("source", one(me.source), one(other.source)),
            *traits("format", one(me.format), one(other.format)),
        ]
        out.append(GalaxyNeighbourOut(
            **other._mapping,
            shared=sorted(
                (s for s in shared if s.chance <= SHARED_CHANCE_MAX),
                key=lambda s: (s.chance, s.kind, (s.name or "").casefold()),
            )[:SHARED_SHOWN],
        ))
    return out


async def place_unplaced(db: AsyncSession) -> int:
    """Put anime the live map has no star for onto it, leaving every other star where it
    is."""
    anime_ids = await galaxy_dao.unplaced_anime_ids(db)
    if not anime_ids:
        return 0
    fit = await galaxy_dao.live_models(db)
    # A map a queued or running rebuild will replace, or one whose `built_from` no longer
    # matches, takes no new stars: the rebuild places everyone.
    if (
        fit is None
        or not is_current(fit)
        or await JobDAO().count_active_by_kind(db, JobKind.galaxy_rebuild)
    ):
        return 0
    anime, media = await galaxy_dao.load_catalogue(db, anime_ids)
    # Don't hold the read transaction open across the child.
    await db.commit()
    stars = await run_in_child(galaxy_compute.place, fit.models, anime, media)
    await galaxy_dao.add_stars(db, fit.id, stars)
    await db.commit()
    logger.info("Placed %d anime onto the galaxy map", len(stars))
    return len(stars)
