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
from app.services import merge_candidate_service, merge_detection_service

require_admin = require_roles(RoleType.Admin)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get(
    "/merge-candidates",
    response_model=list[admin_schema.MergeCandidateListItem],
)
async def list_merge_candidates(db: AsyncSession = Depends(get_db)):
    return await merge_candidate_service.list_pending(db)


@router.post(
    "/merge-candidates/backfill",
    response_model=admin_schema.MergeBackfillResult,
)
async def rerun_merge_detection(db: AsyncSession = Depends(get_db)):
    """Re-run existing × existing detection on demand. Restore doesn't
    bounce the container so the lifespan-startup backfill never sees the
    restored catalog; this endpoint is admin's escape hatch. Idempotent:
    pairs already flagged (any status) are skipped via seen_pairs."""
    inserted = await merge_detection_service.backfill_merge_candidates(db)
    return admin_schema.MergeBackfillResult(inserted=inserted)


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


@router.get(
    "/merge-candidates/dismissed",
    response_model=list[admin_schema.MergeCandidateListItem],
)
async def list_dismissed_merge_candidates(db: AsyncSession = Depends(get_db)):
    """Past dismissals, newest first, for the 'Dismissed decisions' history.
    Deleting one (below) lets the pair resurface on the next detection."""
    return await merge_candidate_service.list_dismissed(db)


@router.post(
    "/merge-candidates/{uuid}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_merge_decision(
    uuid: UUID,
    data: admin_schema.DeleteDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Delete a dismissed decision (username-gated) so it can resurface."""
    await merge_candidate_service.delete_decision(
        db, uuid, confirm=data.confirm, username=current_user.username,
    )
