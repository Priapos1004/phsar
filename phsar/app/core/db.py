from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

DATABASE_URL = (
    f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
)

engine = create_async_engine(DATABASE_URL, echo=settings.DEBUG)

# async_sessionmaker rather than sessionmaker(class_=AsyncSession): the latter's
# TypeVar is bound to Session, which AsyncSession does not subclass, so every
# `async with async_session_maker()` would hand back a session of unknown type.
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative root for every model.

    A real class rather than `declarative_base()`, which is annotated `-> Any`:
    every model would inherit that fallback, `Mapped[...]` annotations would carry
    no information, and a DAO generic could not tell a Media from a Ratings.
    """
