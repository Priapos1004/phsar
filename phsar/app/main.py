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
from app.core.maintenance import is_maintenance_active
from app.daos.job_dao import JobDAO
from app.exceptions import PhsarBaseError
from app.models.job import JobKind
from app.seeders.embedding_backfiller import backfill_embeddings
from app.seeders.genre_seeder import seed_genres
from app.seeders.user_seeder import (
    backfill_spoiler_visibility,
    backfill_user_settings,
    seed_admin_user,
    seed_guest_user,
)
from app.services.job_worker import job_worker
from app.services.merge_detection_service import backfill_merge_candidates
from app.services.scrape_dispatcher import user_scrape_dispatcher

setup_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting up FastAPI app")

    async with async_session_maker() as session:
        await seed_genres(session)
        await seed_admin_user(session)
        await seed_guest_user(session)
        await backfill_user_settings(session)
        await backfill_spoiler_visibility(session)
        await backfill_embeddings(session)
        await backfill_merge_candidates(session)
        # Mark anything left in `running` as failed — the previous process
        # died mid-job, so the row is stale. User retries from the bell.
        reaped = await JobDAO().reap_orphans(session)
        if reaped:
            await session.commit()
            logger.warning("Reaped %d orphan running jobs from previous process", reaped)

    job_worker.register_dispatcher(JobKind.user_scrape, user_scrape_dispatcher)
    await job_worker.start()

    yield  # Startup complete

    await job_worker.stop()
    logger.info("🛑 Shutting down FastAPI app")

def create_app() -> FastAPI:
    app = FastAPI(
        title="phsar - Anime Ratings",
        version="1.0.0",
        lifespan=lifespan,
    )

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

    @app.middleware("http")
    async def maintenance_gate(request: Request, call_next):
        # /, /health stay open so Coolify's liveness check doesn't fail the
        # container mid-window and trigger a restart in the middle of an
        # operation. /maintenance/status stays open so the frontend's banner
        # can keep polling truthful state while the rest of the API is 503'd
        # — without it, the user lands on /login?maintenance=1 with no
        # countdown to tell them when service resumes.
        if is_maintenance_active() and request.url.path not in (
            "/",
            "/health",
            "/maintenance/status",
        ):
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Maintenance in progress. Please try again in a moment.",
                    "maintenance": True,
                },
            )
        return await call_next(request)

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