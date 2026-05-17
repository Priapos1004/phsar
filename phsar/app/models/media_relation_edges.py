"""Per-media MAL relation edges captured at scrape time.

Sidecar to `media`. Kept off the canonical row so anime detail / search
hot paths via `selectinload(Anime.media)` don't drag the JSONB through
every page load. The two-pass relation classifier reads via explicit
`selectinload(Media.relation_edges)` at merge / preview / backfill time.

See `MediaFreshness` for the broader sidecar rationale.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class MediaRelationEdges(BaseModel):
    __tablename__ = "media_relation_edges"

    media_id = Column(
        Integer,
        ForeignKey("media.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # List of [target_mal_id, normalized_relation] pairs. `target_mal_id`
    # may point outside the local catalog (BFS frontier) — no FK.
    edges = Column(JSONB, nullable=False, default=list, server_default="[]")
    # Last time the edges were synced from MAL (lifespan backfill,
    # save_service, or update_sweep step 1). NULL means never fetched;
    # the backfiller's gate uses this to distinguish "we got back an
    # empty relations list" from "we haven't asked MAL yet" — without
    # it the falsy-empty-list check re-fetched standalone anime on
    # every restart.
    last_fetched_at = Column(DateTime(timezone=True), nullable=True)

    media = relationship("Media", back_populates="relation_edges", lazy="raise")
