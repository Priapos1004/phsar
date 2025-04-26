import uuid

from sqlalchemy import Column, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class BaseModel(Base):
    __abstract__ = True

    id = Column(Integer, primary_key=True, index=True) # Primary key
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False) # Public safe identifier
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False) # When inserted
    modified_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False) # When updated
