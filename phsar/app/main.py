from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import \
    models  # Make sure models are loaded for Alembic to recognize them


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP LOGIC ---
    print("🚀 App starting")

    yield

    # --- SHUTDOWN LOGIC ---
    print("🛑 App shutting down")


app = FastAPI(title="phsar - Anime Ratings", lifespan=lifespan)

@app.get("/")
def root():
    return {"message": "Anime API is live :-)"}
