import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.logging_config import setup_logging
from app.exceptions import PhsarBaseError
from app.seeders.anime_search_seeder import seed_anime_embeddings
from app.seeders.genre_seeder import seed_genres
from app.seeders.user_seeder import seed_admin_user

setup_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting up FastAPI app")

    async with async_session_maker() as session:
        await seed_genres(session)
        await seed_admin_user(session)
        await seed_anime_embeddings(session)

    yield  # Startup complete

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
    )

    @app.exception_handler(PhsarBaseError)
    async def phsar_exception_handler(request: Request, exc: PhsarBaseError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})
    

    # Local import to avoid early dependency resolution in tests
    from app.routers import auth, filters, media, ratings, save, search, seeder

    app.include_router(auth.router)
    app.include_router(filters.router)
    app.include_router(media.router)
    app.include_router(ratings.router)
    app.include_router(save.router)
    app.include_router(search.router)
    app.include_router(seeder.router)

    @app.get("/")
    async def root():
        return {"message": "Anime API is live :-)"}

    return app

app = create_app()