"""Per-media freshness state for the nightly update sweep.

Sidecar to `media`. The sweep refreshes each child media of a due anime
independently (one /anime/{id}/full call per media) so a newly-added
media on an otherwise-stable anime doesn't pull the parent back into
tier 2. Backfilled to `media.created_at` by the 7a migration.

See `AnimeFreshness` for the broader sidecar rationale.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer
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

    media = relationship("Media", back_populates="freshness", lazy="raise")
