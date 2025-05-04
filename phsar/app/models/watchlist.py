from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
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

    # Optional note field
    note = Column(String(1000), nullable=True)

    # Optional priority field: 1 (high), 2 (medium), 3 (low)
    priority = Column(Integer, nullable=True)
    __table_args__ = (
        UniqueConstraint('user_id', 'media_id', name='unique_user_media_watchlist'),
        CheckConstraint("priority >= 1 AND priority <= 3", name="priority_range_check"),
    )

    # Relationships
    media = relationship("Media", back_populates="watchlist")
    users = relationship("Users", back_populates="watchlist")
    watchlist_tag = relationship("WatchlistTag", back_populates="watchlist", cascade="all, delete-orphan")
