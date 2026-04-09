from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel

from app.models.users import RoleType


class ExpiryPreset(int, Enum):
    """Allowed token expiry durations in days."""
    one_day = 1
    one_week = 7
    one_month = 30


class RegistrationTokenCreateRequest(BaseModel):
    role: RoleType
    expires_in_days: ExpiryPreset = ExpiryPreset.one_week


class RegistrationTokenListItem(BaseModel):
    uuid: str
    token: str
    role: RoleType
    status: Literal["active", "used", "expired"]
    created_by: str
    created_at: datetime
    expires_on: datetime
    used_by: str | None = None
    used_at: datetime | None = None
