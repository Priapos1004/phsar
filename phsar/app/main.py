import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.db import async_session_maker
from app.core.logging_config import setup_logging
from app.exceptions import (
    AnimeNotFoundError,
    CouldNotValidateCredentialsError,
    InsufficientPermissionsError,
    MainMediaNotFoundError,
    MalIdAlreadyExistsError,
    PhsarBaseError,
)
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
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handlers
    @app.exception_handler(PhsarBaseError)
    async def phsar_base_exception_handler(request: Request, exc: PhsarBaseError):
        # Default response for all custom exceptions, override per type if needed
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_exception_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    
    @app.exception_handler(CouldNotValidateCredentialsError)
    async def could_not_validate_credentials_exception_handler(request: Request, exc: CouldNotValidateCredentialsError):
        return JSONResponse(status_code=401, content={"detail": str(exc)})
    
    @app.exception_handler(InsufficientPermissionsError)
    async def insufficient_permissions_exception_handler(request: Request, exc: InsufficientPermissionsError):
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    
    @app.exception_handler(MainMediaNotFoundError)
    async def main_media_not_found_exception_handler(request: Request, exc: MainMediaNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    
    @app.exception_handler(AnimeNotFoundError)
    async def anime_not_found_exception_handler(request: Request, exc: AnimeNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    
    @app.exception_handler(MalIdAlreadyExistsError)
    async def mal_id_already_exists_exception_handler(request: Request, exc: MalIdAlreadyExistsError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    

    # Local import to avoid early dependency resolution in tests
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

app = create_app()