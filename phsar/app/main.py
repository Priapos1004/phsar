import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # Make sure models are loaded for Alembic
from app.core.db import async_session_maker
from app.core.logging_config import setup_logging
from app.routers import search
from app.seeders.genre_seeder import seed_genres
from app.seeders.user_seeder import seed_admin_user

setup_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP LOGIC ---
    logger.info("🚀 App starting")
    async with async_session_maker() as session:
        await seed_genres(session)
        await seed_admin_user(session)

    yield

    # --- SHUTDOWN LOGIC ---
    logger.info("🛑 App shutting down")

app = FastAPI(title="phsar - Anime Ratings", lifespan=lifespan)

# Register all routers
app.include_router(search.router)

@app.get("/")
async def root():
    return {"message": "Anime API is live :-)"}