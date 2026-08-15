import uuid

from sqlalchemy import Column, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class BaseModel(Base):
    __abstract__ = True

    # Primary key. Deliberately NOT index=True — the PRIMARY KEY constraint
    # already builds its own unique btree, so adding one here gives every table
    # a second identical index: dead weight on reads, write amplification on
    # every INSERT.
    id = Column(Integer, primary_key=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False) # Public safe identifier
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False) # When inserted
    modified_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False) # When updated
