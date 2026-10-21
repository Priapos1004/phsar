from datetime import date

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.discover_progress import DiscoverProgress


class DiscoverProgressDAO(BaseDAO[DiscoverProgress]):
    def __init__(self):
        super().__init__(DiscoverProgress)

    async def record_spin(self, db: AsyncSession, user_id: int, day: date, world: str) -> tuple[int, str]:
        """Count the user's spin on `day`, once however often they spin that day, keeping
        `world` as the day's draw; returns their spin count and the day's world. One
        statement, so two spins racing on a new day count once and keep one world. Only a
        later day counts, so a spin sent before midnight that commits after one sent past it
        neither counts again nor moves the day back."""
        # In ON CONFLICT's SET, every column reads the row as it stood before the update.
        new_day = DiscoverProgress.spun_on < day
        stmt = (
            pg_insert(DiscoverProgress)
            .values(user_id=user_id, spin_count=1, spun_on=day, world=world)
            .on_conflict_do_update(
                index_elements=[DiscoverProgress.user_id],
                set_={
                    "spin_count": DiscoverProgress.spin_count + case((new_day, 1), else_=0),
                    "world": case((new_day, world), else_=DiscoverProgress.world),
                    "spun_on": func.greatest(DiscoverProgress.spun_on, day),
                    # ON CONFLICT runs no `onupdate`, so the timestamp is set by hand.
                    "modified_at": func.now(),
                },
            )
            .returning(DiscoverProgress.spin_count, DiscoverProgress.world)
        )
        return (await db.execute(stmt)).tuples().one()
