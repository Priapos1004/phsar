from typing import Generic, TypeVar

from sqlalchemy import delete, distinct, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta
from sqlalchemy.sql.sqltypes import Float, Integer, Numeric

from app.exceptions import FieldDoesNotExistError, NonNumericFieldError

T = TypeVar("T", bound=DeclarativeMeta)  # any SQLAlchemy model


def recency_order(model, column: str = "modified_at") -> tuple:
    """`(<column> DESC, id DESC)` — newest-first WITH a primary-key tiebreak.

    Every newest-first ordering needs the tiebreak, because the timestamps tie by
    construction, not by coincidence: a bulk rate stamps one `modified_at` across
    every media in an anime, and a seasonal sweep bulk-inserts hundreds of child
    jobs in one transaction, so `server_default=func.now()` gives them all the
    same `created_at`.

    Without a tiebreak the consequences differ by query but are never benign. An
    unpaginated list reshuffles tied rows between identical requests. A
    *paginated* one is worse: the sort is free to place a tied row differently
    per page fetch, so the same row can appear on page 1 and again on page 2 —
    or be skipped entirely.

    Pass `column="created_at"` for insertion-ordered listings.
    """
    return (getattr(model, column).desc(), model.id.desc())

class BaseDAO(Generic[T]):
    def __init__(self, model: type[T]):
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

    async def get_all_by_field(self, db: AsyncSession, field_name: str, values: list) -> list[T]:
        if not values:
            return []
        field = getattr(self.model, field_name, None)
        if field is None:
            raise FieldDoesNotExistError(field_name, self.model.__name__)
        result = await db.execute(select(self.model).where(field.in_(values)))
        return result.scalars().all()

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
    
    async def get_unique_in_fields(self, db: AsyncSession, field_names: list[str], order: bool = True) -> list[tuple]:
        """
        Get distinct values from specific fields in the model.
        Optionally order the results (default: True).
        """
        fields = [getattr(self.model, field_name) for field_name in field_names]
        stmt = select(*fields).distinct()
        if order:
            stmt = stmt.order_by(*fields)
        result = await db.execute(stmt)
        return [tuple(row) for row in result.fetchall()]
    
    async def get_min_max(self, db: AsyncSession, field_name: str) -> tuple:
        """The (min, max) bounds of a numeric field — one query, two aggregates.

        Kept deliberately narrow rather than routed through a general
        "field stats" helper: the sole caller is the filter-slider bounds in
        `filter_service`, which reads exactly these two values, and computing
        avg/stddev/median alongside costs a second query per field (the
        `percentile_cont` median needs its own sort) for numbers nothing reads —
        four such per `/filters/options?view_type=media`. Add other statistics
        only together with a caller that reads them.

        `hasattr` as well as `mapper.columns`, so a hybrid with a SQL expression
        (`Media.total_watch_time`) resolves — the media filter bounds need it.
        """
        if field_name not in inspect(self.model).columns and not hasattr(self.model, field_name):
            raise FieldDoesNotExistError(field_name, self.model.__name__)
        field = getattr(self.model, field_name)
        if type(field.type) not in (Integer, Float, Numeric):
            raise NonNumericFieldError(field_name)

        row = (await db.execute(select(func.min(field), func.max(field)))).one()
        return row[0], row[1]
