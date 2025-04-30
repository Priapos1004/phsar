from typing import Generic, Type, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta

T = TypeVar("T", bound=DeclarativeMeta)  # any SQLAlchemy model

class BaseDAO(Generic[T]):
    def __init__(self, model: Type[T]):
        self.model = model

    async def get_by_id(self, db: AsyncSession, id: int) -> T | None:
        result = await db.execute(select(self.model).filter_by(id=id))
        return result.scalars().first()

    async def get_by_field(self, db: AsyncSession, **kwargs) -> T | None:
        result = await db.execute(select(self.model).filter_by(**kwargs))
        return result.scalars().first()

    async def create(self, db: AsyncSession, obj: T) -> T:
        db.add(obj)
        await db.flush()
        return obj

    async def delete(self, db: AsyncSession, obj: T) -> None:
        await db.delete(obj)
        await db.flush()

    async def delete_all_by_field(self, db: AsyncSession, field_name: str, values: list) -> None:
        if not values:
            return
        field = getattr(self.model, field_name)
        stmt = delete(self.model).where(field.in_(values))
        await db.execute(stmt)
        await db.flush()
