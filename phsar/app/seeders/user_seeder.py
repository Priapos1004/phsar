import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.users import RoleType, Users

logger = logging.getLogger(__name__)

async def seed_admin_user(db: AsyncSession):
    # Look for the admin user by username
    result = await db.execute(select(Users).where(Users.username == settings.ADMIN_USERNAME))
    admin_user = result.scalars().first()

    if not admin_user:
        hashed_password = get_password_hash(settings.ADMIN_PASSWORD)
        new_admin = Users(
            username=settings.ADMIN_USERNAME,
            hashed_password=hashed_password,
            role=RoleType.Admin  # Set admin role
        )
        db.add(new_admin)
        await db.commit()
        logger.info(f"Admin user '{settings.ADMIN_USERNAME}' created.")
    else:
        logger.info(f"Admin user '{settings.ADMIN_USERNAME}' already exists.")
