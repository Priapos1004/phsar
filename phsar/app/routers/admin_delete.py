"""Admin delete-candidate review endpoints.

Powered by delete_candidate_service: detection raises, an admin decides here —
`docs/features/curation.md`.

Mounted under `/admin` by the parent router. Router-level admin dep so each
handler doesn't repeat the `Depends(require_admin)` declaration.

Note the two verbs. `/remove` APPLIES a candidate (deletes the media); `/delete`
deletes a dismissed *decision* so it can resurface. `/delete` is the shared name
across all three curation queues — the frontend's DismissedDecisionsSection
posts to it generically — so the apply verb is the one that had to differ, the
same way merge and split use `/merge` and `/split`.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.users import RoleType
from app.schemas import admin_schema
from app.services import delete_candidate_service

require_admin = require_roles(RoleType.Admin)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get(
    "/delete-candidates",
    response_model=list[admin_schema.DeleteCandidateListItem],
)
async def list_delete_candidates(db: AsyncSession = Depends(get_db)):
    return await delete_candidate_service.list_pending(db)


@router.post(
    "/delete-candidates/backfill",
    response_model=admin_schema.DeleteBackfillResult,
)
async def rerun_delete_detection(db: AsyncSession = Depends(get_db)):
    """Re-run the low-signal pass on demand. The sweep runs it nightly, but a
    restore doesn't bounce the container, so a freshly-restored catalogue would
    otherwise show an empty queue until the next sweep. Idempotent: mal_ids
    carrying a live decision are skipped.

    The 404 detector is not re-runnable here — it only observes what a live MAL
    refresh returns, so it belongs to the sweep.
    """
    inserted = await delete_candidate_service.detect_low_signal_candidates(db)
    await db.commit()
    return admin_schema.DeleteBackfillResult(inserted=inserted)


@router.post(
    "/delete-candidates/{uuid}/remove",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_delete_candidate(
    uuid: UUID,
    data: admin_schema.DeleteCandidateRemoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Apply a candidate: delete the media, and its anime if that was the last
    one. Username-gated — the cascade takes the user data on that media with it
    and there is no undo short of a backup restore. `blacklist` additionally
    blocks rediscovery."""
    await delete_candidate_service.remove(
        db,
        uuid,
        confirm=data.confirm,
        username=current_user.username,
        blacklist=data.blacklist,
    )


@router.post(
    "/delete-candidates/{uuid}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def dismiss_delete_candidate(uuid: UUID, db: AsyncSession = Depends(get_db)):
    await delete_candidate_service.dismiss(db, uuid)


@router.get(
    "/delete-candidates/dismissed",
    response_model=list[admin_schema.DeleteCandidateListItem],
)
async def list_dismissed_delete_candidates(db: AsyncSession = Depends(get_db)):
    """Past keep-it decisions, newest first. Deleting one (below) lets the entry
    resurface on the next detection."""
    return await delete_candidate_service.list_dismissed(db)


@router.post(
    "/delete-candidates/{uuid}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_delete_decision(
    uuid: UUID, db: AsyncSession = Depends(get_db),
):
    """Delete a dismissed decision so it can resurface on the next detection."""
    await delete_candidate_service.delete_decision(db, uuid)
