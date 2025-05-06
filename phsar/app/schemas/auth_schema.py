from datetime import datetime

from pydantic import BaseModel

from app.models.users import RoleType


class UserCreate(BaseModel):
    username: str
    password: str

class UserCreateWithToken(BaseModel):
    username: str
    password: str
    registration_token: str

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenValidationResponse(BaseModel):
    is_valid: bool

class RegistrationTokenCreate(BaseModel):
    role: RoleType

class RegistrationTokenResponse(BaseModel):
    token: str
    role: RoleType
    created_by: str
    expires_on: datetime
