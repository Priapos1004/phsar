"""How far a user has spun Discover's wheel of worlds (docs/features/browse.md).

Sidecar to `users` (`.claude/rules/database.md`). A user without a row has never spun.
"""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.users import Users


class DiscoverProgress(BaseModel):
    __tablename__ = "discover_progress"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False,
    )
    # Spins so far, at most one per UTC day; the draw's position in the user's bag.
    spin_count: Mapped[int] = mapped_column(Integer, nullable=False)
    spun_on: Mapped[date] = mapped_column(Date, nullable=False)

    users: Mapped["Users"] = relationship("Users", back_populates="discover_progress", lazy="raise")
