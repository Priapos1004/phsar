from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.browse import BrowseCarousel, CarouselFilterSet


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
