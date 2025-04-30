import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import DATABASE_URL
from app.core.dependencies import get_db
from app.main import create_app

# Create a new engine just for tests
engine = create_async_engine(DATABASE_URL, future=True)

# Test session maker using test engine
TestSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

@pytest.fixture
async def db_session():
    # Connect directly to DB and begin a transaction
    async with engine.connect() as conn:
        # Begin a transaction on the raw connection
        trans = await conn.begin()

        # Bind a session to the connection, inside the transaction
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            yield session

        # Roll back at the connection level (undo ALL commits)
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
