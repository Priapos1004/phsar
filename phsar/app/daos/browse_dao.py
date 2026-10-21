from collections.abc import Iterable
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.browse import BrowseCarousel, CarouselFilterSet
from app.models.discover_progress import DiscoverProgress


class BrowseCarouselDAO(BaseDAO[BrowseCarousel]):
    def __init__(self):
        super().__init__(BrowseCarousel)

    async def get_with_filter_sets(
        self, db: AsyncSession, keys: Iterable[str] | None = None,
    ) -> dict[str, BrowseCarousel]:
        """The carousels named (every one without `keys`), keyed by `key`, each with its
        offered filter sets loaded in `position` order."""
        stmt = select(BrowseCarousel).options(
            selectinload(BrowseCarousel.filter_sets).selectinload(CarouselFilterSet.filter_set),
        )
        if keys is not None:
            stmt = stmt.where(BrowseCarousel.key.in_(list(keys)))
        return {c.key: c for c in (await db.execute(stmt)).scalars().all()}


class DiscoverProgressDAO(BaseDAO[DiscoverProgress]):
    def __init__(self):
        super().__init__(DiscoverProgress)

    async def record_spin(self, db: AsyncSession, user_id: int, day: date) -> int:
        """Count the user's spin on `day`, once however often they spin that day; returns
        their spin count. One statement, so two spins racing on a new day count once."""
        stmt = (
            pg_insert(DiscoverProgress)
            .values(user_id=user_id, spin_count=1, spun_on=day)
            .on_conflict_do_update(
                index_elements=[DiscoverProgress.user_id],
                set_={
                    "spin_count": DiscoverProgress.spin_count + case((DiscoverProgress.spun_on != day, 1), else_=0),
                    "spun_on": day,
                    # ON CONFLICT runs no `onupdate`, so the timestamp is set by hand.
                    "modified_at": func.now(),
                },
            )
            .returning(DiscoverProgress.spin_count)
        )
        return (await db.execute(stmt)).scalar_one()
