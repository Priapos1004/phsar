import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    DUMMY_HASH,
    get_password_hash,
    needs_rehash,
    verify_password,
)
from app.models.registration_token import RegistrationToken
from app.models.users import RoleType, Users
from app.schemas.auth_schema import UserCreateWithToken

logger = logging.getLogger(__name__)

class AuthService:
    @staticmethod
    async def register(user_data: UserCreateWithToken, db: AsyncSession):
        # Check if username already exists
        result = await db.execute(select(Users).filter_by(username=user_data.username))
        existing_user = result.scalars().first()
        if existing_user:
            raise ValueError(f"Username '{user_data.username}' already registered.")

        # Validate registration token
        result = await db.execute(select(RegistrationToken).filter_by(token=user_data.registration_token))
        token_obj = result.scalars().first()
        if not token_obj:
            raise ValueError("Invalid registration token.")
        if token_obj.was_used_for_user_id is not None:
            raise ValueError("This registration token has already been used.")
        if token_obj.is_expired:
            raise ValueError("This registration token has expired.")

        # Create new user with role from token
        hashed_pw = get_password_hash(user_data.password)
        new_user = Users(
            username=user_data.username,
            hashed_password=hashed_pw,
            role=token_obj.role  # take role from token
        )
        db.add(new_user)
        await db.flush()  # So new_user.id is available

        # Mark the token as used
        token_obj.was_used_for_user_id = new_user.id
        token_obj.used_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(new_user)
        return new_user

    @staticmethod
    async def authenticate(username: str, password: str, db: AsyncSession):
        # Fetch user
        result = await db.execute(select(Users).filter_by(username=username))
        user = result.scalars().first()

        # Choose which hash to verify against (real or dummy), then verify ONCE
        hash_to_check = user.hashed_password if user else DUMMY_HASH
        ok = verify_password(password, hash_to_check)

        # Single rejection check
        if (not ok) or (user is None):
            return None

        # Optional: seamless rehash if your policy changed
        if needs_rehash(user.hashed_password):
            new_hash = get_password_hash(password)
            try:
                # Conditional UPDATE to avoid clobbering if another request already rehashed
                stmt = (
                    update(Users)
                    .where(
                        Users.id == user.id,
                        Users.hashed_password == user.hashed_password,  # Race guard
                    )
                    .values(
                        hashed_password=new_hash
                    )
                )
                result = await db.execute(stmt)
                # If exactly one row updated, reflect the change in the in-memory object
                if getattr(result, "rowcount", None) == 1:
                    user.hashed_password = new_hash
                    logger.info("Password hash rehashed for user_name=%s", user.username)
                await db.commit()
            except Exception:
                # If anything goes wrong, don’t block login — just roll back the upgrade
                await db.rollback()
                logger.exception("Failed to rehash password for user_name=%s", user.username)

        return user
    
    @staticmethod
    async def create_registration_token(role: RoleType, created_by_user: Users, db: AsyncSession, expires_in_days: int = 7):
        token_str = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        new_token = RegistrationToken(
            token=token_str,
            created_by_user_id=created_by_user.id,
            role=role,
            expires_on=now + timedelta(days=expires_in_days)
        )
        db.add(new_token)
        await db.commit()
        await db.refresh(new_token)
        return new_token
