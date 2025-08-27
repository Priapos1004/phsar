from typing import AsyncGenerator, Union

# app/core/dependencies.py
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.security import decompress_and_decode
from app.exceptions import (
    CouldNotValidateCredentialsError,
    InsufficientPermissionsError,
    MalformedTokenError,
    MissingSearchDataError,
    TokenVersionMismatchError,
)
from app.models.users import Users

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
    result = await db.execute(select(Users).filter_by(username=username))
    user = result.scalars().first()
    if user is None:
        raise CouldNotValidateCredentialsError()
    return user

def require_roles(allowed_roles: Union[str, list[str]]):
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]

    async def role_checker(current_user = Depends(get_current_user)):
        if current_user.role.value not in allowed_roles:
            raise InsufficientPermissionsError()
        return current_user

    return role_checker


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
