from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.job_dao import JobDAO
from app.daos.registration_token_dao import RegistrationTokenDAO
from app.exceptions import CannotDeleteUsedTokenError, RegistrationTokenNotFoundError
from app.models.job import Job, JobKind, JobStatus
from app.models.registration_token import RegistrationToken
from app.schemas.admin_schema import RegistrationTokenListItem
from app.schemas.job_schema import AdminJobResponse, AdminJobsPage

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
    """Flatten the requested_by relationship to a username so the admin
    Jobs Log can render attribution without a per-row join client-side.
    System jobs (cron + seasonal-sweep children) have requested_by_user_id
    NULL → username surfaces as null (rendered as 'system' on the frontend).

    Explicit field-by-field construction mirrors `_token_to_list_item` —
    `model_validate(job.__dict__)` would skip SQLAlchemy's lazy-attribute
    machinery and surface internal state, and `model_validate(job)` with
    `from_attributes=True` can't supply the synthetic
    `requested_by_username` field."""
    return AdminJobResponse(
        uuid=job.uuid,
        kind=job.kind,
        status=job.status,
        payload=job.payload,
        stage=job.stage,
        items_total=job.items_total,
        items_done=job.items_done,
        result_summary=job.result_summary,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        requested_by_username=job.requested_by.username if job.requested_by else None,
    )


async def list_jobs_paginated(
    db: AsyncSession,
    *,
    status: JobStatus | None,
    kind: JobKind | None,
    user_id: int | None,
    created_after: datetime | None,
    created_before: datetime | None,
    limit: int,
    offset: int,
) -> AdminJobsPage:
    items, total = await job_dao.list_admin_paginated(
        db,
        status=status, kind=kind, user_id=user_id,
        created_after=created_after, created_before=created_before,
        limit=limit, offset=offset,
    )
    return AdminJobsPage(
        items=[_job_to_admin_response(j) for j in items],
        total=total,
        limit=limit,
        offset=offset,
    )
