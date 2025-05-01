import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import DATABASE_URL
from app.core.dependencies import get_db
from app.main import create_app


@pytest.fixture
async def db_engine():
    # Move engine creation inside the loop
    engine = create_async_engine(DATABASE_URL, future=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    # Create session maker inside fixture
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        async_session = sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)

        try:
            async with async_session() as session:
                yield session
        finally:
            # Always rollback even if test fails
            await trans.rollback()


@pytest.fixture
async def client(db_session):
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
