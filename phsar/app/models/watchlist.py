from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Watchlist(BaseModel):
    __tablename__ = "watchlist"

    # Foreign Key Media and Users
    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Exactly one tag per entry (v0.15.0 — replaced the WatchlistTag many-to-many).
    # ON DELETE CASCADE: deleting a tag removes its entries unless the service reassigns
    # them to the default tag first (the delete-with-reassign path).
    tag_id = Column(Integer, ForeignKey("tag.id", ondelete="CASCADE"), nullable=False)

    # Optional note field
    note = Column(String(1000), nullable=True)

    # Priority: 1 (high), 2 (medium), 3 (low). Non-optional — the UI defaults to 3 so the
    # user never has to touch it, but a value is always stored.
    priority = Column(Integer, nullable=False, server_default="3")
    __table_args__ = (
        UniqueConstraint('user_id', 'media_id', name='unique_user_media_watchlist'),
        CheckConstraint("priority >= 1 AND priority <= 3", name="priority_range_check"),
    )

    # Relationships
    media = relationship("Media", back_populates="watchlist", lazy="raise")
    users = relationship("Users", back_populates="watchlist", lazy="raise")
    tag = relationship("Tag", back_populates="watchlist", lazy="raise")


# Composite index for paginated listing: WHERE user_id = ? ORDER BY modified_at DESC
Index("ix_watchlist_user_modified", Watchlist.user_id, Watchlist.modified_at.desc())
