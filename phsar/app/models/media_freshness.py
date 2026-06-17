"""Per-media freshness state for the nightly update sweep.

Sidecar to `media`. As of v0.14.8 the sweep *selects* work at media
granularity (`AnimeDAO.select_due_media_for_sweep`): only the media that
are individually due get refreshed, so a still-airing umbrella no longer
drags its stable old members through a /anime/{id}/full call every night.
`last_checked_at` + `stable_check_count` are this media's own refresh
clock (mirroring `AnimeFreshness`, which is now purely the per-anime
*probe* clock). Backfilled to `media.created_at` by the 7a migration;
`stable_check_count` added (server_default 0) by the v0.14.8 migration.

See `AnimeFreshness` for the broader sidecar rationale.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class MediaFreshness(BaseModel):
    __tablename__ = "media_freshness"

    media_id = Column(
        Integer,
        ForeignKey("media.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    # Per-media stability counter (v0.14.8). Resets to 0 when a refresh
    # observes a volatile-field delta on this media or it is currently
    # airing; otherwise climbs. Media-level tier 2 (count < 5) burns the
    # initial stability sampling. Server-default 0 so existing rows enter
    # the rotation un-stabilized without an explicit backfill UPDATE.
    stable_check_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    media = relationship("Media", back_populates="freshness", lazy="raise")
