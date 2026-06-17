"""Per-anime freshness state for the nightly update sweep.

Sidecar to `anime`. Splitting these columns out keeps the canonical anime
row narrow and stops sweep state from leaking into Pydantic response
schemas via accidental `model_dump()` use.

`last_checked_at` is NULL only between insert and the first sweep that
touches the row — production rows are backfilled to `anime.created_at` by
the 7a migration so they enter the rotation at their honest age, not
"brand new". `stable_check_count` resets to 0 whenever a refresh observes
any field delta on the anime's media; tier 2 of the sweep
(count < SWEEP_STABILIZE_THRESHOLD) burns through the initial stability
sampling for fresh rows. As of v0.14.8 this counter is the per-anime *probe*
clock — MediaFreshness drives per-media refresh selection.

`unique=True` on `anime_id` enforces the 1:1 invariant — the synthetic
`id` from BaseModel keeps the row addressable and gives us audit
timestamps (`created_at`/`modified_at`) for debugging when sweep behavior
diverges from expectations. Matches the unique-FK pattern used in the
other 1:1 sidecars (`anime_search`, `media_search`).
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class AnimeFreshness(BaseModel):
    __tablename__ = "anime_freshness"

    anime_id = Column(
        Integer,
        ForeignKey("anime.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    stable_check_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    anime = relationship("Anime", back_populates="freshness", lazy="raise")
