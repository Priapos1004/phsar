from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Ratings(BaseModel):
    __tablename__ = "ratings"

    # Rating: float between 0 and 10
    rating = Column(Float, nullable=False)

    # Foreign Key Media and Users
    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('user_id', 'media_id', name='unique_user_media_rating'),
        CheckConstraint("rating >= 0 AND rating <= 10", name="rating_range_check"),
    )

    # Optional note field
    note = Column(String(1000), nullable=True)

    # Number of episodes watched (can be used to infer dropped)
    episodes_watched = Column(Integer, nullable=True)

    # Explicitly track whether the user dropped the anime
    dropped = Column(Boolean, default=False)

    # Relationships
    media = relationship("Media", back_populates="ratings")
    users = relationship("Users", back_populates="ratings")
