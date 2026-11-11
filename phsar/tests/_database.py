"""The suite's own database, rebuilt from nothing at the start of every session: dropped,
created, migrated to head — the schema prod runs, built the way prod builds it — and
seeded with what the tests read. Fresh each run, so rows a test committed and failed to
clean up never reach the next."""

import asyncio
from pathlib import Path

from alembic.command import upgrade
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401 — every model registered before the seeders map theirs
from app.core.config import settings
from app.core.db import async_session_maker, engine
from app.seeders.genre_seeder import seed_genres
from app.seeders.user_seeder import seed_admin_user


def alembic_config() -> Config:
    """The deploy's own `alembic.ini`, so the suite replays the chain the way a deploy does."""
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["configure_logger"] = False
    return config


def build() -> None:
    # The guard that keeps a misconfiguration off the dev database: only a database named
    # for the suite is the suite's to drop. It reads the engine's database, the one every
    # test connects to, so an import that built the engine before `tests/__init__` renamed
    # the database is refused too.
    name = engine.url.database
    if name != settings.DB_NAME or not name.endswith("_test"):
        raise RuntimeError(f"Refusing to rebuild {name!r}: the suite only drops its own database, named *_test.")
    asyncio.run(_recreate(name))
    # Between the two loops: `alembic/env.py` runs its own.
    upgrade(alembic_config(), "head")
    asyncio.run(_seed())


async def _recreate(name: str) -> None:
    server = create_async_engine(engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with server.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await server.dispose()


async def _seed() -> None:
    async with async_session_maker() as session:
        await seed_genres(session)
        await seed_admin_user(session)
    # Its connections belong to this loop; each test runs on its own.
    await engine.dispose()
