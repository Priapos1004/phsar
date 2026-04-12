"""Precomputed spoiler visibility cache.

Stores which media are visible (not spoiler-protected) for each user.
Recomputed per-anime when a user rates or deletes a rating.
Seeded for new users with the first main media of each anime.

This is a cache table — no uuid/timestamps needed. Uses a simple
composite primary key for fast bulk delete + insert.
"""

from sqlalchemy import Column, ForeignKey, Index, Integer, UniqueConstraint

from app.core.db import Base


class UserVisibleMedia(Base):
    __tablename__ = "user_visible_media"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "media_id", name="uq_user_visible_media"),
        Index("ix_user_visible_media_user_id", "user_id"),
    )
