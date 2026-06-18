"""Admin split-candidate review endpoints.

Powered by find_disjoint_franchises (in app/services/relation_classifier.py)
and the SplitCandidate row queue. Detection runs at three call sites
(scrape, relation-backfiller's per-anime loop, merge survivor);
admins use these endpoints to triage the flagged anime — execute the
split or dismiss.

Mounted under `/admin` by the parent router. Router-level admin dep so
each handler doesn't repeat `Depends(require_admin)`.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.users import RoleType
from app.schemas import admin_schema
from app.seeders.split_candidate_backfiller import backfill_split_candidates
from app.services import split_candidate_service

require_admin = require_roles(RoleType.Admin)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get(
    "/split-candidates",
    response_model=list[admin_schema.SplitCandidateListItem],
)
async def list_split_candidates(db: AsyncSession = Depends(get_db)):
    return await split_candidate_service.list_pending(db)


@router.post(
    "/split-candidates/backfill",
    response_model=admin_schema.SplitBackfillResult,
)
async def rerun_split_detection(db: AsyncSession = Depends(get_db)):
    """Re-run disjoint-franchise detection over the full catalog on
    demand. The lifespan-startup backfill catches most cases; this is
    admin's escape hatch for re-running after a manual data fix or a
    bug-fix deploy that changes detection semantics. Idempotent."""
    summary = await backfill_split_candidates(db)
    await db.commit()
    return admin_schema.SplitBackfillResult(inserted=summary["candidates_inserted"])


@router.post(
    "/split-candidates/{uuid}/split",
    response_model=admin_schema.SplitResult,
)
async def split_anime_candidate(uuid: UUID, db: AsyncSession = Depends(get_db)):
    surviving_uuid, new_anime_uuids = await split_candidate_service.execute_split(
        db, uuid,
    )
    return admin_schema.SplitResult(
        surviving_anime_uuid=surviving_uuid,
        new_anime_uuids=new_anime_uuids,
    )


@router.post(
    "/split-candidates/{uuid}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def dismiss_split_candidate(uuid: UUID, db: AsyncSession = Depends(get_db)):
    await split_candidate_service.dismiss(db, uuid)


@router.get(
    "/split-candidates/dismissed",
    response_model=list[admin_schema.SplitCandidateListItem],
)
async def list_dismissed_split_candidates(db: AsyncSession = Depends(get_db)):
    """Past dismissals, newest first. Deleting one (below) lets it resurface
    on the next detection."""
    return await split_candidate_service.list_dismissed(db)


@router.post(
    "/split-candidates/{uuid}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_split_decision(
    uuid: UUID,
    data: admin_schema.DeleteDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Delete a dismissed decision (username-gated) so it can resurface."""
    await split_candidate_service.delete_decision(
        db, uuid, confirm=data.confirm, username=current_user.username,
    )
