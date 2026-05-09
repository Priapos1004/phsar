"""Top-level pytest fixtures.

DB fixtures live here so non-router tests (services, daos) can use them too.
Router-specific fixtures (auth headers, client, etc.) stay in
tests/routers/conftest.py.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import DATABASE_URL


@pytest.fixture
async def db_engine():
    engine = create_async_engine(DATABASE_URL, future=True)
    yield engine
    await engine.dispose()


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
