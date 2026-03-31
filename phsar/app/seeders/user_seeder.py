import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash
from app.daos.user_dao import UserDAO
from app.models.users import RoleType, Users

logger = logging.getLogger(__name__)

user_dao = UserDAO()

async def seed_admin_user(db: AsyncSession):
    admin_user = await user_dao.get_by_username(db, settings.ADMIN_USERNAME)

    if not admin_user:
        hashed_password = get_password_hash(settings.ADMIN_PASSWORD)
        new_admin = Users(
            username=settings.ADMIN_USERNAME,
            hashed_password=hashed_password,
            role=RoleType.Admin  # Set admin role
        )
        await user_dao.create(db, new_admin)
        await db.commit()
        logger.info(f"Admin user '{settings.ADMIN_USERNAME}' created.")
    else:
        logger.info(f"Admin user '{settings.ADMIN_USERNAME}' already exists.")
