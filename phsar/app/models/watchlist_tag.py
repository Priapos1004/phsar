from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class WatchlistTag(BaseModel):
    __tablename__ = "watchlist_tag"

    watchlist_id = Column(Integer, ForeignKey("watchlist.id", ondelete="CASCADE"))
    tag_id = Column(Integer, ForeignKey("tag.id", ondelete="CASCADE"))
    __table_args__ = (
        UniqueConstraint('watchlist_id', 'tag_id', name='unique_watchlist_tag'),
    )
    # Relationships
    watchlist = relationship("Watchlist", back_populates="watchlist_tag", lazy="raise")
    tag = relationship("Tag", back_populates="watchlist_tag", lazy="raise")
