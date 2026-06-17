import logging

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash
from app.daos.user_dao import UserDAO
from app.models.user_settings import SpoilerLevel, UserSettings
from app.models.user_visible_media import UserVisibleMedia
from app.models.users import RoleType, Users
from app.services import user_settings_service
from app.services.spoiler_service import recompute_visibility_for_user

logger = logging.getLogger(__name__)

user_dao = UserDAO()


async def _seed_user(
    db: AsyncSession, username: str, password: str, role: RoleType
):
    """Create a user with default settings if they don't exist yet."""
    existing = await user_dao.get_by_username(db, username)
    if existing:
        logger.info(f"User '{username}' already exists.")
        return

    hashed_password = get_password_hash(password)
    new_user = Users(
        username=username,
        hashed_password=hashed_password,
        role=role,
    )
    await user_dao.create(db, new_user)
    await user_settings_service.create_default_settings(db, new_user.id)
    # Restricted users are pinned to spoiler=off and never read the cache,
    # so don't build one (it would also be re-seeded every startup by
    # backfill_spoiler_visibility, which skips them too).
    if role != RoleType.RestrictedUser:
        await recompute_visibility_for_user(db, new_user.id)
    await db.commit()
    logger.info(f"User '{username}' created with role '{role.value}'.")


async def seed_admin_user(db: AsyncSession):
    await _seed_user(db, settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD, RoleType.Admin)


async def seed_guest_user(db: AsyncSession):
    if not settings.GUEST_USERNAME or not settings.GUEST_PASSWORD:
        logger.info("Guest credentials not configured, skipping guest seeder.")
        return
    await _seed_user(db, settings.GUEST_USERNAME, settings.GUEST_PASSWORD, RoleType.RestrictedUser)


async def backfill_spoiler_visibility(db: AsyncSession):
    """Recompute spoiler visibility for users who have no rows in user_visible_media.
    Covers new deployments and users created before the feature existed.

    This is the ONLY whole-catalog recompute path — post-mutation recomputes
    are scoped via `spoiler_service.refresh_spoiler_cache_for_anime_ids`. It's
    also the mop-up for any non-restricted user a scoped recompute skipped on
    failure. Per-user try/commit so a poisoned user (stale rating FKs, etc.)
    doesn't abort startup — it can't itself be fragile."""
    # Exclude restricted users: they're pinned to spoiler=off and never
    # read the cache, so they'd otherwise show up here every startup
    # (always zero rows) and get re-seeded for nothing.
    stmt = (
        select(Users.id)
        .outerjoin(UserVisibleMedia, Users.id == UserVisibleMedia.user_id)
        .where(
            UserVisibleMedia.id.is_(None),
            Users.role != RoleType.RestrictedUser,
        )
    )
    result = await db.execute(stmt)
    user_ids = result.scalars().all()

    if not user_ids:
        return

    succeeded = 0
    for user_id in user_ids:
        try:
            await recompute_visibility_for_user(db, user_id)
            await db.commit()
            succeeded += 1
        except Exception:
            await db.rollback()
            logger.exception("Spoiler-visibility backfill failed for user %s", user_id)
    logger.info(f"Backfilled spoiler visibility for {succeeded}/{len(user_ids)} user(s).")


async def purge_restricted_user_spoiler_cache(db: AsyncSession):
    """Pin restricted (guest) users to spoiler=off at startup: reset any
    legacy non-off `spoiler_level` AND delete any `user_visible_media` rows
    belonging to them. They're pinned to off and excluded from the cache as
    of v0.14.7, but a user demoted to `restricted_user` while holding
    `hide`/`blur` would otherwise keep that value (the settings-update path
    only blocks *new* changes) — and since they're purged from the cache, a
    lingering `hide` would read an empty cache and blank the catalogue.
    Resetting the setting here repairs legacy rows without the user having to
    touch settings. Idempotent: touches zero rows once clean."""
    restricted_ids = select(Users.id).where(Users.role == RoleType.RestrictedUser)
    reset = await db.execute(
        update(UserSettings)
        .where(
            UserSettings.user_id.in_(restricted_ids),
            UserSettings.spoiler_level != SpoilerLevel.off,
        )
        .values(spoiler_level=SpoilerLevel.off)
    )
    result = await db.execute(
        delete(UserVisibleMedia).where(UserVisibleMedia.user_id.in_(restricted_ids))
    )
    await db.commit()
    if reset.rowcount:
        logger.info(
            "Reset %d restricted-user spoiler_level value(s) to off.", reset.rowcount,
        )
    if result.rowcount:
        logger.info(
            "Purged %d restricted-user spoiler-cache row(s).", result.rowcount,
        )


async def backfill_user_settings(db: AsyncSession):
    """Create default UserSettings for any users that don't have them yet."""
    stmt = (
        select(Users.id)
        .outerjoin(UserSettings, Users.id == UserSettings.user_id)
        .where(UserSettings.id.is_(None))
    )
    result = await db.execute(stmt)
    user_ids = result.scalars().all()

    if not user_ids:
        return

    for user_id in user_ids:
        await user_settings_service.create_default_settings(db, user_id)
    await db.commit()
    logger.info(f"Backfilled UserSettings for {len(user_ids)} user(s).")
