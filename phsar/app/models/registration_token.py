from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from app.models.base import BaseModel
from app.models.users import RoleType


class RegistrationToken(BaseModel):
    __tablename__ = "registration_token"

    token = Column(String, unique=True, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(Enum(RoleType), nullable=False)
    was_used_for_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True, default=None)
    expires_on = Column(DateTime(timezone=True), nullable=False)

    @hybrid_property
    def is_expired(self):
        return self.expires_on < datetime.now(timezone.utc)

    @is_expired.expression
    def is_expired(cls):
        return cls.expires_on < func.now()

    # Relationships
    created_by = relationship("Users", foreign_keys=[created_by_user_id], back_populates="registration_tokens")
    used_for_user = relationship("Users", foreign_keys=[was_used_for_user_id])
