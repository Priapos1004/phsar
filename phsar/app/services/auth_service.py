import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    DUMMY_HASH,
    get_password_hash,
    needs_rehash,
    verify_password,
)
from app.daos.registration_token_dao import RegistrationTokenDAO
from app.daos.user_dao import UserDAO
from app.exceptions import (
    InvalidPasswordError,
    InvalidRegistrationTokenError,
    RegistrationTokenAlreadyUsedError,
    RegistrationTokenExpiredError,
    UserAlreadyExistsError,
)
from app.models.registration_token import RegistrationToken
from app.models.users import RoleType, Users
from app.schemas.auth_schema import UserCreateWithToken
from app.services import user_settings_service

logger = logging.getLogger(__name__)

user_dao = UserDAO()
registration_token_dao = RegistrationTokenDAO()


async def register(user_data: UserCreateWithToken, db: AsyncSession):
    existing_user = await user_dao.get_by_username(db, user_data.username)
    if existing_user:
        raise UserAlreadyExistsError(user_data.username)

    token_obj = await registration_token_dao.get_by_token(db, user_data.registration_token)
    if not token_obj:
        raise InvalidRegistrationTokenError()
    if token_obj.was_used_for_user_id is not None:
        raise RegistrationTokenAlreadyUsedError()
    if token_obj.is_expired:
        raise RegistrationTokenExpiredError()

    hashed_pw = get_password_hash(user_data.password)
    new_user = Users(
        username=user_data.username,
        hashed_password=hashed_pw,
        role=token_obj.role,
    )
    await user_dao.create(db, new_user)
    await user_settings_service.create_default_settings(db, new_user.id)

    token_obj.was_used_for_user_id = new_user.id
    token_obj.used_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(new_user)
    return new_user


async def authenticate(username: str, password: str, db: AsyncSession):
    user = await user_dao.get_by_username(db, username)

    hash_to_check = user.hashed_password if user else DUMMY_HASH
    ok = verify_password(password, hash_to_check)

    if (not ok) or (user is None):
        return None

    if needs_rehash(user.hashed_password):
        new_hash = get_password_hash(password)
        try:
            updated = await user_dao.update_password_hash(
                db, user.id, user.hashed_password, new_hash
            )
            if updated:
                user.hashed_password = new_hash
                logger.info("Password hash rehashed for user_name=%s", user.username)
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            logger.exception("Failed to rehash password for user_name=%s", user.username)
            user = await user_dao.get_by_username(db, username)

    return user


async def delete_account(user: Users, password: str, db: AsyncSession) -> None:
    """Delete user account after verifying password. DB cascades handle related data."""
    if not verify_password(password, user.hashed_password):
        raise InvalidPasswordError()
    await user_dao.delete(db, user)
    await db.commit()


async def create_registration_token(
    role: RoleType, created_by_user: Users, db: AsyncSession, expires_in_days: int = 7
):
    token_str = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    new_token = RegistrationToken(
        token=token_str,
        created_by_user_id=created_by_user.id,
        role=role,
        expires_on=now + timedelta(days=expires_in_days),
    )
    await registration_token_dao.create(db, new_token)
    await db.commit()
    await db.refresh(new_token)
    return new_token
