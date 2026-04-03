from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Tag(BaseModel):
    __tablename__ = "tag"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(50), nullable=False)
    color = Column(String(7), nullable=False, default="#808080")  # Default: gray

    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='unique_user_tag'),
    )
    # Relationships
    users = relationship("Users", back_populates="tag", lazy="raise")
    watchlist_tag = relationship("WatchlistTag", back_populates="tag", cascade="all, delete-orphan", lazy="raise")
