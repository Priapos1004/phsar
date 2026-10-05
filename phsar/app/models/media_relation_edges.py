"""Per-media MAL relation edges captured at scrape time.

Sidecar to `media`. Kept off the canonical row so anime detail / search
hot paths via `selectinload(Anime.media)` don't drag the JSONB through
every page load. The two-pass relation classifier reads via explicit
`selectinload(Media.relation_edges)` at merge / preview / backfill time.

See `MediaFreshness` for the broader sidecar rationale.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.media import Media


class MediaRelationEdges(BaseModel):
    __tablename__ = "media_relation_edges"

    media_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("media.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # List of [target_mal_id, normalized_relation] pairs. `target_mal_id`
    # may point outside the local catalog (BFS frontier) — no FK. Typed loosely
    # on purpose: each pair is positionally (int, str), which a list annotation
    # cannot express — `list[int | str]` types the union rather than the
    # positions, so every unpack downstream becomes `int | str` and needs a cast. A
    # list rather than a tuple because JSONB round-trips it as one either way.
    edges: Mapped[list[list[Any]]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # Last time the edges were synced from MAL (lifespan backfill,
    # save_service, or update_sweep step 1). NULL means never fetched;
    # the backfiller's gate uses this to distinguish "we got back an
    # empty relations list" from "we haven't asked MAL yet" — without
    # it the falsy-empty-list check re-fetched standalone anime on
    # every restart.
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    media: Mapped["Media"] = relationship("Media", back_populates="relation_edges", lazy="raise")
