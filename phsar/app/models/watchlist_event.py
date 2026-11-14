"""The watchlist's history, written only by the `watchlist_events_log` trigger:
docs/features/recommender.md, "The watchlist's history"."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel, enum_values


class WatchlistEventKind(str, enum.Enum):
    ADDED = "added"
    CHANGED = "changed"
    REMOVED = "removed"


class WatchlistEvent(BaseModel):
    """An entry's state after the event — for a removal, the state it removed. `at` is when it
    happened, a merged event's latest write; `created_at` when the row was first logged."""

    __tablename__ = "watchlist_events"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    media_id: Mapped[int] = mapped_column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[WatchlistEventKind] = mapped_column(
        Enum(WatchlistEventKind, name="watchlist_event_kind", values_callable=enum_values),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    tag_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tag.id", ondelete="SET NULL"), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# The trigger's lookup of an entry's latest events, and a user's rows.
Index("ix_watchlist_events_user_media_at", WatchlistEvent.user_id, WatchlistEvent.media_id, WatchlistEvent.at)
