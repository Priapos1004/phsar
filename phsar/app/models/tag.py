from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Tag(BaseModel):
    __tablename__ = "tag"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(50), nullable=False)
    color = Column(String(7), nullable=False, server_default="#808080", default="#808080")  # Default: gray

    # The immutable per-user default tag ("Watchlist"): can't be renamed, recolored,
    # or deleted, so the UI always has a stable tag to preselect and there's always a
    # reassign target when another tag is deleted. Exactly one per user (partial index).
    is_default = Column(Boolean, nullable=False, server_default="false", default=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='unique_user_tag'),
        # At most one default tag per user.
        Index(
            "uq_tag_one_default_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )
    # Relationships
    users = relationship("Users", back_populates="tag", lazy="raise")
    # One tag → many watchlist entries. No ORM delete-cascade here: deletion is handled
    # by the tag_id FK's ON DELETE CASCADE (cascade path) or an explicit reassign in the
    # service (reassign path); this relationship exists for reads only.
    watchlist = relationship("Watchlist", back_populates="tag", lazy="raise")
