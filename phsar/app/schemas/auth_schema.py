import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.users import RoleType

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_username(v: str) -> str:
    if not USERNAME_PATTERN.match(v):
        raise ValueError("Username may only contain letters, numbers, underscores, and hyphens.")
    return v


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return _validate_username(v)

class UserCreateWithToken(UserCreate):
    registration_token: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenPayload(BaseModel):
    token: str

class TokenValidationResponse(BaseModel):
    is_valid: bool

class RegistrationTokenResponse(BaseModel):
    token: str
    role: RoleType
    created_by: str
    expires_on: datetime


class DeleteAccountRequest(BaseModel):
    password: str
