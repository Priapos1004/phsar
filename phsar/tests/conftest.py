"""Top-level pytest fixtures.

DB fixtures live here so non-router tests (services, daos) can use them too.
Router-specific fixtures (auth headers, client, etc.) stay in
tests/routers/conftest.py.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core import maintenance
from app.core.db import DATABASE_URL, engine as global_engine


@pytest.fixture(autouse=True)
def reset_maintenance_state():
    """Globals — a stray flag from one test would 503 every subsequent
    test in the run, so reset around every test by default. The reset is
    free when no test touched the flags."""
    maintenance.set_maintenance(False)
    maintenance.set_scheduled_at(None)
    yield
    maintenance.set_maintenance(False)
    maintenance.set_scheduled_at(None)


async def _drain_async_close() -> None:
    """asyncpg schedules `_call_connection_lost` via `call_soon` when
    `connection.close()` runs. The callback executes on the next loop
    iteration, but pytest-asyncio gives each test its own event loop
    and closes it as soon as the test coroutine returns — if dispose's
    deferred close-chain hasn't unwound by then, the transport's
    `__del__` fires `ResourceWarning: unclosed transport` and the trace
    "Event loop is closed" appears under teardown. A single `sleep(0)`
    yields to the loop long enough for the chain to complete."""
    await asyncio.sleep(0)


@pytest.fixture(autouse=True)
async def _reset_global_engine_pool():
    """Each pytest-asyncio test gets a fresh event loop; asyncpg refuses
    pooled connections bound to a different loop. Dispose before + after
    so the next test acquires fresh connections AND this test's
    connections close cleanly (see `_drain_async_close`). Autouse across
    the suite — dispose is cheap on an empty pool, so tests that don't
    touch the global engine pay no real cost."""
    await global_engine.dispose()
    yield
    await global_engine.dispose()
    await _drain_async_close()


@pytest.fixture
async def db_engine():
    engine = create_async_engine(DATABASE_URL, future=True)
    yield engine
    await engine.dispose()
    await _drain_async_close()


@pytest.fixture
async def db_session(db_engine):
    """A session whose changes are rolled back at the end of the test.

    PostgreSQL sequences (auto-increment IDs) do NOT roll back, so production
    IDs accumulate gaps from test runs — that's OK; tests should never assert
    on specific PK values.
    """
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        async_session = sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)
        try:
            async with async_session() as session:
                yield session
        finally:
            await trans.rollback()
