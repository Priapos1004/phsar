"""Append-only watch/rewatch event log (v0.14.10).

One row per time a user *completed* a media — the first completion plus every
later rewatch. Keyed to (user_id, media_id) rather than to a rating row so the
history survives a rating being deleted and re-added: `watched_count` is derived
as COUNT(events), never denormalized onto Ratings.

`watched_at` is the event timestamp (kept distinct from BaseModel.created_at so a
backfilled or back-dated event can carry its real watch date) — it's what future
time-series forecasting of watch behaviour reads.

Both FKs are ON DELETE CASCADE so account deletion / media removal clean up at the
DB level; deleting a *rating* does NOT touch events unless the user opts in (see
`rating_service.delete_rating`). No ORM back-relationships on Users/Media — the log
is only ever read via grouped count queries in `WatchEventDAO`, never traversed.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, func

from app.models.base import BaseModel


class WatchEvent(BaseModel):
    __tablename__ = "watch_events"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    # The watch/completion moment. Defaults to now() for live events; settable so a
    # backfill can stamp the originating rating's created_at.
    watched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


# (user_id, media_id) drives the derived watched_count lookups; watched_at drives
# the time-series reads.
Index("ix_watch_events_user_media", WatchEvent.user_id, WatchEvent.media_id)
Index("ix_watch_events_watched_at", WatchEvent.watched_at)
