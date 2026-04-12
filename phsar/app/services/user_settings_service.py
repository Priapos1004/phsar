import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.user_settings_dao import UserSettingsDAO
from app.exceptions import UserSettingsNotFoundError
from app.models.user_settings import UserSettings
from app.schemas.user_settings_schema import UserSettingsOut, UserSettingsUpdate

logger = logging.getLogger(__name__)

user_settings_dao = UserSettingsDAO()


async def get_settings(db: AsyncSession, user_id: int) -> UserSettingsOut:
    settings = await user_settings_dao.get_by_user_id(db, user_id)
    if not settings:
        raise UserSettingsNotFoundError()
    return UserSettingsOut.model_validate(settings)


async def update_settings(
    db: AsyncSession, user_id: int, data: UserSettingsUpdate
) -> UserSettingsOut:
    settings = await user_settings_dao.get_by_user_id(db, user_id)
    if not settings:
        raise UserSettingsNotFoundError()

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(settings, field, value)

    await db.commit()
    await db.refresh(settings)
    return UserSettingsOut.model_validate(settings)


async def create_default_settings(db: AsyncSession, user_id: int) -> UserSettings:
    """Create a UserSettings row with all defaults if one doesn't exist yet."""
    existing = await user_settings_dao.get_by_user_id(db, user_id)
    if existing:
        return existing
    new_settings = UserSettings(user_id=user_id)
    return await user_settings_dao.create(db, new_settings)
