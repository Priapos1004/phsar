import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _validate_name(v: str) -> str:
    name = v.strip()
    if not name:
        raise ValueError("Tag name cannot be empty")
    if len(name) > 50:
        raise ValueError("Tag name must be at most 50 characters")
    return name


def _validate_color(v: str) -> str:
    if not _HEX_COLOR.match(v):
        raise ValueError("Color must be a hex value like #RRGGBB")
    return v.lower()


class TagCreate(BaseModel):
    name: str
    color: str

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return _validate_name(v)

    @field_validator("color")
    @classmethod
    def check_color(cls, v: str) -> str:
        return _validate_color(v)


class TagUpdate(BaseModel):
    """Partial update — only the provided fields change. Blocked entirely for the
    default tag in the service."""
    name: str | None = None
    color: str | None = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str | None) -> str | None:
        return _validate_name(v) if v is not None else v

    @field_validator("color")
    @classmethod
    def check_color(cls, v: str | None) -> str | None:
        return _validate_color(v) if v is not None else v


class TagOut(BaseModel):
    uuid: UUID
    name: str
    color: str
    is_default: bool
    # entry_count = watchlist entries under this tag (media); anime_count = distinct
    # anime among them (drives the removal-count guard for empty/delete). Not ORM
    # columns — set by the service from a grouped count query.
    entry_count: int = 0
    anime_count: int = 0
    created_at: datetime
    modified_at: datetime

    model_config = ConfigDict(from_attributes=True)
