from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (create_access_token, get_password_hash,
                               verify_password)
from app.models.users import Users
from app.schemas.auth_schema import UserCreate


class AuthService:
    @staticmethod
    async def register(user_data: UserCreate, db: AsyncSession):
        result = await db.execute(select(Users).filter_by(username=user_data.username))
        existing_user = result.scalars().first()
        if existing_user:
            raise ValueError(f"Username '{user_data.username}' already registered.")
        
        hashed_pw = get_password_hash(user_data.password)
        new_user = Users(username=user_data.username, hashed_password=hashed_pw)
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return new_user

    @staticmethod
    async def authenticate(username: str, password: str, db: AsyncSession):
        result = await db.execute(select(Users).filter_by(username=username))
        user = result.scalars().first()
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user
