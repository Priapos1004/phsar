import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.logging_config import setup_logging
from app.core.maintenance import get_scheduled_at, is_maintenance_active
from app.core.maintenance_middleware import MaintenanceGateMiddleware
from app.daos.job_dao import JobDAO
from app.exceptions import PhsarBaseError
from app.models.job import JobKind
from app.seeders.anime_title_backfiller import backfill_anime_title_suffixes
from app.seeders.embedding_backfiller import backfill_embeddings
from app.seeders.genre_seeder import seed_genres
from app.seeders.relation_backfiller import backfill_relations
from app.seeders.split_candidate_backfiller import backfill_split_candidates
from app.seeders.user_seeder import (
    backfill_spoiler_visibility,
    backfill_user_settings,
    seed_admin_user,
    seed_guest_user,
)
from app.services.backup_dispatcher import backup_dispatcher
from app.services.job_worker import job_worker
from app.services.merge_detection_service import backfill_merge_candidates
from app.services.scrape_dispatcher import (
    update_sweep_dispatcher,
    user_scrape_dispatcher,
)
from app.services.seasonal_sweep_dispatcher import seasonal_sweep_dispatcher

setup_logging()
logger = logging.getLogger(__name__)

async def _post_yield_backfills() -> None:
    """Long-running catalog backfills that must not block /health.

    On the first v0.14.1 deploy against an existing v0.14.0 DB the
    relation backfiller lazy-fetches missing MediaRelationEdges from MAL
    at ~1 req/s — ~14 min for an 800-media catalog. Running synchronously
    in lifespan would starve Coolify's liveness probe and trigger a
    restart loop. Fired as `asyncio.create_task` after `yield` so the
    HTTP layer responds immediately; per-anime commit checkpoints in
    `backfill_relations` already tolerate abrupt termination.

    Merge-candidate detection runs AFTER relation backfill so it sees
    the rewritten relation types in the title-similarity signal. While
    the task is in flight, save-time merge detection (inside
    `save_search_results`) still works against the pre-backfill catalog
    — the task's tail re-runs detection at the end, so any pre-backfill
    miss self-heals.

    Each pass runs in its own session so the identity map doesn't grow
    across the three catalog-wide scans — the relation backfill loads
    every Anime + Media + sidecar, and reusing one session for all three
    would pin ~3× the working set in memory through the whole ~14-min
    cold start.
    """
    try:
        if settings.RELATION_BACKFILL_ON_STARTUP:
            async with async_session_maker() as session:
                await backfill_relations(session)
        async with async_session_maker() as session:
            await backfill_merge_candidates(session)
            await session.commit()
        async with async_session_maker() as session:
            # Split-detection runs LAST so it sees the rewritten relation
            # types from relation_backfiller AND any merges resolved by
            # backfill_merge_candidates collapsed pairs (which removes
            # would-be duplicate split-candidates). When the per-anime
            # hook inside relation_backfiller already covered every row,
            # this is a no-op pass — upsert_pending is idempotent on
            # identical cluster payloads.
            await backfill_split_candidates(session)
            await session.commit()
    except asyncio.CancelledError:
        logger.info("Post-yield backfill cancelled by shutdown")
        raise
    except Exception:
        logger.exception("Post-yield backfill failed — catalog hygiene incomplete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting up FastAPI app")
    # Paired with the set_maintenance flip log: ops can grep these two
    # to tell "container restarted" from "flag stuck across restarts".
    logger.info(
        "Maintenance state at startup: active=%s, scheduled_at=%s",
        is_maintenance_active(), get_scheduled_at(),
    )

    async with async_session_maker() as session:
        await seed_genres(session)
        await seed_admin_user(session)
        await seed_guest_user(session)
        await backfill_user_settings(session)
        await backfill_spoiler_visibility(session)
        # Title-suffix stripper runs BEFORE the embedding backfiller so a
        # row whose suffix is stripped here gets its regenerated embedding
        # immediately. The embedding backfiller below covers the
        # missing-embedding case (model swap / new rows without a
        # search row); these two passes are independent.
        await backfill_anime_title_suffixes(session)
        await backfill_embeddings(session)
        # Mark anything left in `running` as failed — the previous process
        # died mid-job, so the row is stale. User retries from the bell.
        reaped = await JobDAO().reap_orphans(session)
        if reaped:
            await session.commit()
            logger.warning("Reaped %d orphan running jobs from previous process", reaped)

    job_worker.register_dispatcher(JobKind.user_scrape, user_scrape_dispatcher)
    job_worker.register_dispatcher(JobKind.update_sweep, update_sweep_dispatcher)
    job_worker.register_dispatcher(JobKind.seasonal_sweep, seasonal_sweep_dispatcher)
    job_worker.register_dispatcher(JobKind.backup, backup_dispatcher)
    await job_worker.start()

    backfill_task = asyncio.create_task(_post_yield_backfills())

    yield  # Startup complete — /health responds even while backfill runs

    backfill_task.cancel()
    try:
        await backfill_task
    except asyncio.CancelledError:
        pass
    # Any non-cancellation exception was already logged by the task's
    # own except clause; letting it propagate here would just abort
    # shutdown after job_worker.stop() never ran, so we trust the task
    # to log and swallow.
    await job_worker.stop()
    logger.info("🛑 Shutting down FastAPI app")

def create_app() -> FastAPI:
    app = FastAPI(
        title="phsar - Anime Ratings",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Order matters: app.add_middleware insert(0, ...)s, so the LAST one
    # registered ends up OUTERMOST. We need CORS outside the maintenance
    # gate so 503 short-circuits still carry Access-Control-Allow-Origin —
    # otherwise cross-origin fetch() rejects with a TypeError instead of a
    # 503 response, and the frontend's catch falls into the generic
    # "unexpected error" branch instead of the maintenance-banner branch.
    app.add_middleware(MaintenanceGateMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Browsers hide Content-Disposition from cross-origin fetch() unless it's
        # explicitly exposed — the frontend's downloadBlob parses it for the filename.
        expose_headers=["Content-Disposition"],
    )

    @app.exception_handler(PhsarBaseError)
    async def phsar_exception_handler(request: Request, exc: PhsarBaseError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    # Local import to avoid early dependency resolution in tests
    from app.routers import (
        admin,
        auth,
        filters,
        jobs,
        library,
        maintenance,
        media,
        ratings,
        save,
        search,
        seeder,
        users,
    )

    app.include_router(admin.router)
    app.include_router(auth.router)
    app.include_router(filters.router)
    app.include_router(jobs.router)
    app.include_router(library.router)
    app.include_router(maintenance.router)
    app.include_router(media.router)
    app.include_router(ratings.router)
    app.include_router(save.router)
    app.include_router(search.router)
    app.include_router(seeder.router)
    app.include_router(users.router)

    @app.get("/")
    async def root():
        return {"message": "Anime API is live :-)"}

    @app.get("/health")
    async def health():
        # Short-circuit the normal get_db dependency and time-box the ping
        # ourselves — asyncpg's connect timeout is ~60s, which makes Coolify's
        # liveness probe slow-503 during transient DB unavailability instead
        # of fast-503. A bounded ping keeps liveness responsive.
        async def _ping_db() -> bool:
            async with async_session_maker() as session:
                await session.execute(text("SELECT 1"))
                return True

        try:
            db_ok = await asyncio.wait_for(_ping_db(), timeout=2.0)
        except Exception:
            db_ok = False
        return JSONResponse(
            status_code=200 if db_ok else 503,
            content={
                "status": "ok" if db_ok else "degraded",
                "version": settings.APP_VERSION,
                "db": "ok" if db_ok else "error",
            },
        )

    return app

app = create_app()