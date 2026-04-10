import enum

from sqlalchemy import Column, Enum, String
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class RoleType(str, enum.Enum):
    RestrictedUser = "restricted_user"
    User = "user"
    Admin = "admin"

# Named "Users" (plural) to avoid conflicts with the reserved keyword "user" in SQL
class Users(BaseModel):
    __tablename__ = "users"

    username = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(RoleType), nullable=False, default=RoleType.User)

    # Relationships
    ratings = relationship("Ratings", back_populates="users", cascade="all, delete-orphan", lazy="raise")
    watchlist = relationship("Watchlist", back_populates="users", cascade="all, delete-orphan", lazy="raise")
    tag = relationship("Tag", back_populates="users", cascade="all, delete-orphan", lazy="raise")
    registration_tokens = relationship(
        "RegistrationToken",
        back_populates="created_by",
        foreign_keys="[RegistrationToken.created_by_user_id]",
        passive_deletes=True,
        lazy="raise",
    )
    settings = relationship("UserSettings", back_populates="users", uselist=False, cascade="all, delete-orphan", lazy="raise")
