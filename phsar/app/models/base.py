import uuid
from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BaseModel(Base):
    __abstract__ = True

    # Primary key. Deliberately NOT index=True — the PRIMARY KEY constraint
    # already builds its own unique btree, so adding one here gives every table
    # a second identical index: dead weight on reads, write amplification on
    # every INSERT.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False) # Public safe identifier
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False) # When inserted
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False) # When updated
