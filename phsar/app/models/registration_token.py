from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SQLColumnExpression,
    String,
    func,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.users import RoleType, Users


class RegistrationToken(BaseModel):
    __tablename__ = "registration_token"

    token: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    role: Mapped[RoleType] = mapped_column(Enum(RoleType), nullable=False)
    was_used_for_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    expires_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @hybrid_property
    def is_expired(self) -> bool:
        return self.expires_on < datetime.now(timezone.utc)

    @is_expired.inplace.expression
    @classmethod
    def _is_expired_expression(cls) -> SQLColumnExpression[bool]:
        return cls.expires_on < func.now()

    # Relationships
    created_by: Mapped["Users | None"] = relationship("Users", foreign_keys=[created_by_user_id], back_populates="registration_tokens", lazy="raise")
    used_for_user: Mapped["Users | None"] = relationship("Users", foreign_keys=[was_used_for_user_id], lazy="raise")
