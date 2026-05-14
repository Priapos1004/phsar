"""Admin merge-candidate review endpoints.

Powered by the merge_detection_service — duplicate-anime detection runs
at the end of `save_search_results` and on lifespan startup
(`backfill_merge_candidates`); admins use these endpoints to triage the
flagged pairs (merge or dismiss).

Mounted under `/admin` by the parent router. Router-level admin dep so
each handler doesn't repeat the `Depends(require_admin)` declaration.
"""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.users import RoleType
from app.schemas import admin_schema
from app.services import merge_candidate_service

require_admin = require_roles(RoleType.Admin)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get(
    "/merge-candidates",
    response_model=list[admin_schema.MergeCandidateListItem],
)
async def list_merge_candidates(db: AsyncSession = Depends(get_db)):
    return await merge_candidate_service.list_pending(db)


@router.post(
    "/merge-candidates/{uuid}/merge",
    response_model=admin_schema.MergeResult,
)
async def merge_anime_candidate(
    uuid: UUID,
    data: admin_schema.MergeRequest = Body(default_factory=admin_schema.MergeRequest),
    db: AsyncSession = Depends(get_db),
):
    surviving_uuid = await merge_candidate_service.merge(db, uuid, keep_uuid=data.keep_uuid)
    return admin_schema.MergeResult(surviving_anime_uuid=surviving_uuid)


@router.post(
    "/merge-candidates/{uuid}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def dismiss_anime_candidate(uuid: UUID, db: AsyncSession = Depends(get_db)):
    await merge_candidate_service.dismiss(db, uuid)
