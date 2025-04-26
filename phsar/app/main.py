from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # Make sure models are loaded for Alembic
from app.core.db import async_session_maker
from app.seeders.genre_seeder import seed_genres
from app.seeders.user_seeder import seed_admin_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP LOGIC ---
    print("🚀 App starting")
    async with async_session_maker() as session:
        await seed_genres(session)
        await seed_admin_user(session)

    yield

    # --- SHUTDOWN LOGIC ---
    print("🛑 App shutting down")

app = FastAPI(title="phsar - Anime Ratings", lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "Anime API is live :-)"}