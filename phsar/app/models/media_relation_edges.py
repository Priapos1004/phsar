"""Per-media MAL relation edges captured at scrape time.

Sidecar to `media`. Kept off the canonical row so anime detail / search
hot paths via `selectinload(Anime.media)` don't drag the JSONB through
every page load. The two-pass relation classifier reads via explicit
`selectinload(Media.relation_edges)` at merge / preview / backfill time.

See `MediaFreshness` for the broader sidecar rationale.
"""

from sqlalchemy import Column, ForeignKey, Integer
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

    media = relationship("Media", back_populates="relation_edges", lazy="raise")
