from typing import Generic, Type, TypeVar

from sqlalchemy import delete, distinct, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta
from sqlalchemy.sql.sqltypes import Float, Integer, Numeric

from app.exceptions import NonNumericFieldError

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

    async def get_unique_in_field(self, db: AsyncSession, field_name: str, order: bool = True) -> list:
        """
        Get distinct values from a specific field in the model.
        Optionally order the results (default: True).
        """
        field = getattr(self.model, field_name)
        stmt = select(distinct(field))
        if order:
            stmt = stmt.order_by(field)
        result = await db.execute(stmt)
        return [row[0] for row in result.fetchall()]
    
    async def get_field_stats(self, db: AsyncSession, field_name: str) -> dict:
        """
        Get min, max, avg, stddev, median for a numeric field.
        Raises NonNumericFieldError if the field is not numeric.
        """
        mapper = inspect(self.model)
        if field_name not in mapper.columns and not hasattr(self.model, field_name):
            raise ValueError(f"Field '{field_name}' does not exist in model {self.model.__name__}")

        field = getattr(self.model, field_name)
        field_type = type(field.type)

        if field_type not in (Integer, Float, Numeric):
            raise NonNumericFieldError(field_name)

        # min, max, avg, stddev
        stats_stmt = select(
            func.min(field),
            func.max(field),
            func.avg(field),
            func.stddev_pop(field)
        )
        result = await db.execute(stats_stmt)
        row = result.one_or_none()

        # median (Postgres)
        median_stmt = select(
            func.percentile_cont(0.5).within_group(field)
        )
        median_result = await db.execute(median_stmt)
        median_row = median_result.one_or_none()
        median_value = median_row[0] if median_row else None

        return {
            'min': row[0],
            'max': row[1],
            'avg': row[2],
            'stddev': row[3],
            'median': median_value
        }
    
    async def get_min_max(self, db: AsyncSession, field_name: str) -> tuple:
        stats = await self.get_field_stats(db, field_name)
        return stats['min'], stats['max']
