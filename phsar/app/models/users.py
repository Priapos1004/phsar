import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.ratings import Ratings
    from app.models.registration_token import RegistrationToken
    from app.models.tag import Tag
    from app.models.user_settings import UserSettings
    from app.models.watchlist import Watchlist


class RoleType(str, enum.Enum):
    RestrictedUser = "restricted_user"
    User = "user"
    Admin = "admin"

# Named "Users" (plural) to avoid conflicts with the reserved keyword "user" in SQL
class Users(BaseModel):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[RoleType] = mapped_column(Enum(RoleType), nullable=False, default=RoleType.User)

    # Relationships
    ratings: Mapped[list["Ratings"]] = relationship("Ratings", back_populates="users", cascade="all, delete-orphan", lazy="raise")
    watchlist: Mapped[list["Watchlist"]] = relationship("Watchlist", back_populates="users", cascade="all, delete-orphan", lazy="raise")
    tag: Mapped[list["Tag"]] = relationship("Tag", back_populates="users", cascade="all, delete-orphan", lazy="raise")
    registration_tokens: Mapped[list["RegistrationToken"]] = relationship(
        "RegistrationToken",
        back_populates="created_by",
        foreign_keys="[RegistrationToken.created_by_user_id]",
        passive_deletes=True,
        lazy="raise",
    )
    settings: Mapped["UserSettings | None"] = relationship("UserSettings", back_populates="users", uselist=False, cascade="all, delete-orphan", lazy="raise")
