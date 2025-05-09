import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.db import async_session_maker
from app.core.logging_config import setup_logging
from app.seeders.genre_seeder import seed_genres
from app.seeders.user_seeder import seed_admin_user

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting up FastAPI app")

    # Optional: preloading or health check logic could go here

    async with async_session_maker() as session:
        await seed_genres(session)
        await seed_admin_user(session)

    yield  # <--- Startup complete

    logger.info("🛑 Shutting down FastAPI app")
    # Optional: resource cleanup here (e.g. background task shutdown)


def create_app() -> FastAPI:
    app = FastAPI(
        title="phsar - Anime Ratings",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],  # SvelteKit dev server
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Local import avoids early dependency resolution in tests
    from app.routers import auth, filters, save, search, seeder

    app.include_router(auth.router)
    app.include_router(filters.router)
    app.include_router(save.router)
    app.include_router(search.router)
    app.include_router(seeder.router)

    @app.get("/")
    async def root():
        return {"message": "Anime API is live :-)"}

    return app


# This is the app instance used by Uvicorn/Gunicorn
app = create_app()