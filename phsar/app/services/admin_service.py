from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.job_dao import JobDAO
from app.daos.registration_token_dao import RegistrationTokenDAO
from app.exceptions import (
    CannotDeleteUsedTokenError,
    JobNotFoundError,
    RegistrationTokenNotFoundError,
)
from app.models.job import Job, JobKind, JobStatus
from app.models.registration_token import RegistrationToken
from app.schemas.admin_schema import RegistrationTokenListItem
from app.schemas.job_schema import AdminJobResponse, AdminJobsPage, JobResponse

registration_token_dao = RegistrationTokenDAO()
job_dao = JobDAO()

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
    token = await registration_token_dao.get_by_uuid(db, uuid)
    if not token:
        raise RegistrationTokenNotFoundError(str(uuid))
    if token.used_at is not None:
        raise CannotDeleteUsedTokenError()
    await registration_token_dao.delete(db, token)
    await db.commit()


def _job_to_admin_response(job: Job) -> AdminJobResponse:
    """Validate the inherited columns through JobResponse (its
    `from_attributes=True` config handles the ORM read), then add the
    two synthetic fields. Adding a column to Job + JobResponse picks
    up here for free — no field list to keep in sync."""
    base = JobResponse.model_validate(job).model_dump()
    return AdminJobResponse(
        **base,
        requested_by_username=job.requested_by.username if job.requested_by else None,
        parent_job_uuid=job.parent.uuid if job.parent else None,
    )


async def list_jobs_paginated(
    db: AsyncSession,
    *,
    status: JobStatus | None,
    kind: JobKind | None,
    user_id: int | None,
    created_after: datetime | None,
    created_before: datetime | None,
    parent_uuid: UUID | None,
    limit: int,
    offset: int,
) -> AdminJobsPage:
    """When `parent_uuid` is set, returns only the children of that
    parent. Otherwise filters out child rows (parent_job_id IS NULL) so
    the main Jobs Log isn't dominated by seasonal-sweep children — admin
    expands a sweep row to see them."""
    parent_job_id: int | None = None
    if parent_uuid is not None:
        parent_job = await job_dao.get_by_uuid(db, parent_uuid)
        # Unknown parent → empty page (don't 404; an admin reload after a
        # parent deletion shouldn't break the surrounding view).
        if parent_job is None:
            return AdminJobsPage(items=[], total=0, limit=limit, offset=offset)
        parent_job_id = parent_job.id

    items, total = await job_dao.list_admin_paginated(
        db,
        status=status, kind=kind, user_id=user_id,
        created_after=created_after, created_before=created_before,
        parent_job_id=parent_job_id,
        roots_only=parent_uuid is None,
        limit=limit, offset=offset,
    )
    return AdminJobsPage(
        items=[_job_to_admin_response(j) for j in items],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_job_for_admin(db: AsyncSession, job_uuid: UUID) -> AdminJobResponse:
    """Fetch a single job for the admin detail page. Eager-loads
    `requested_by` + `parent` via the DAO so the response builder can
    fill `requested_by_username` and `parent_job_uuid`."""
    job = await job_dao.get_by_uuid_with_relations(db, job_uuid)
    if job is None:
        raise JobNotFoundError(str(job_uuid))
    return _job_to_admin_response(job)
