import secrets
from typing import AsyncGenerator, Union

from fastapi import Depends, Header
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.security import decompress_and_decode
from app.daos.user_dao import UserDAO
from app.exceptions import (
    CouldNotValidateCredentialsError,
    InsufficientPermissionsError,
    InvalidCronTokenError,
    MalformedTokenError,
    MissingSearchDataError,
    TokenVersionMismatchError,
)
from app.models.users import RoleType, Users

user_dao = UserDAO()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session

async def get_current_user(
    db: AsyncSession = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> Users:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise CouldNotValidateCredentialsError()
    except JWTError:
        raise CouldNotValidateCredentialsError()
    user = await user_dao.get_by_username(db, username)
    if user is None:
        raise CouldNotValidateCredentialsError()
    return user

def require_roles(allowed_roles: Union[RoleType, list[RoleType]]):
    if isinstance(allowed_roles, RoleType):
        allowed_roles = [allowed_roles]

    async def role_checker(current_user = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise InsufficientPermissionsError()
        return current_user

    return role_checker


# Shared role dependency: User and Admin (excludes RestrictedUser)
require_user_or_admin = require_roles([RoleType.User, RoleType.Admin])


def require_backup_cron_token(
    authorization: str | None = Header(default=None),
) -> None:
    """Authenticates the scheduled-backup endpoint via a shared bearer token.
    Fails closed when BACKUP_CRON_TOKEN is unset so an empty secret can't be brute-forced."""
    expected = settings.BACKUP_CRON_TOKEN
    if not expected:
        raise InvalidCronTokenError()
    if not authorization or not authorization.startswith("Bearer "):
        raise InvalidCronTokenError()
    provided = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(provided, expected):
        raise InvalidCronTokenError()


def verify_url_token(token: str) -> dict:
    try:
        # Decode and verify JWT signature
        payload = jwt.decode(
            token,
            settings.SEARCH_SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )

        # Check API version
        payload_version = payload.get("ver")
        if payload_version != settings.CURRENT_SEARCH_API_VERSION:
            raise TokenVersionMismatchError(payload_version)

        # Extract and decompress search data
        compressed_data = payload.get("data")
        if not compressed_data:
            raise MissingSearchDataError()

        return decompress_and_decode(compressed_data)

    except JWTError:
        raise MalformedTokenError()
