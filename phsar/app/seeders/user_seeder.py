from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.users import RoleType, Users

# Password hasher
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def seed_admin_user(db: AsyncSession):
    # Look for the admin user by username
    result = await db.execute(select(Users).where(Users.username == settings.ADMIN_USERNAME))
    admin_user = result.scalars().first()

    if not admin_user:
        hashed_password = pwd_context.hash(settings.ADMIN_PASSWORD)
        new_admin = Users(
            username=settings.ADMIN_USERNAME,
            hashed_password=hashed_password,
            role=RoleType.Admin  # Set admin role
        )
        db.add(new_admin)
        await db.commit()
