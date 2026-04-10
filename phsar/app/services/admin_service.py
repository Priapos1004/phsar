from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.registration_token_dao import RegistrationTokenDAO
from app.exceptions import CannotDeleteUsedTokenError, RegistrationTokenNotFoundError
from app.models.registration_token import RegistrationToken
from app.schemas.admin_schema import RegistrationTokenListItem

registration_token_dao = RegistrationTokenDAO()

DELETED_USER_DISPLAY = "[deleted]"


def _token_status(token: RegistrationToken) -> str:
    # Check used_at (not the FK) because the FK is SET NULL on user deletion
    if token.used_at is not None:
        return "used"
    if token.is_expired:
        return "expired"
    return "active"


def _token_to_list_item(token: RegistrationToken) -> RegistrationTokenListItem:
    return RegistrationTokenListItem(
        uuid=str(token.uuid),
        token=token.token,
        role=token.role,
        status=_token_status(token),
        created_by=token.created_by.username if token.created_by else DELETED_USER_DISPLAY,
        created_at=token.created_at,
        expires_on=token.expires_on,
        used_by=token.used_for_user.username if token.used_for_user else (DELETED_USER_DISPLAY if token.used_at else None),
        used_at=token.used_at,
    )


async def list_registration_tokens(db: AsyncSession) -> list[RegistrationTokenListItem]:
    tokens = await registration_token_dao.get_all_with_users(db)
    return [_token_to_list_item(t) for t in tokens]


async def delete_registration_token(db: AsyncSession, uuid: UUID) -> None:
    token = await registration_token_dao.get_by_uuid(db, str(uuid))
    if not token:
        raise RegistrationTokenNotFoundError(str(uuid))
    if token.used_at is not None:
        raise CannotDeleteUsedTokenError()
    await registration_token_dao.delete(db, token)
    await db.commit()
