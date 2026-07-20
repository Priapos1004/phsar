from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_user_or_admin
from app.schemas import tag_schema
from app.services import tag_service

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


# --- Tags ---

@router.get("/tags", response_model=list[tag_schema.TagOut])
async def list_tags(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """All of the user's tags (default first) with entry + anime counts."""
    return await tag_service.list_tags(db, current_user.id)


@router.post("/tags", response_model=tag_schema.TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    data: tag_schema.TagCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    return await tag_service.create_tag(db, current_user.id, data)


@router.patch("/tags/{uuid}", response_model=tag_schema.TagOut)
async def update_tag(
    uuid: UUID,
    data: tag_schema.TagUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """Rename/recolor a tag. Blocked for the immutable default tag."""
    return await tag_service.update_tag(db, current_user.id, uuid, data)


@router.delete("/tags/{uuid}", status_code=status.HTTP_200_OK)
async def delete_tag(
    uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
    reassign_entries: bool = Query(default=False),
):
    """Delete a non-default tag. `reassign_entries=true` moves its entries to the
    default tag first; otherwise they're deleted with it. Returns entries affected."""
    affected = await tag_service.delete_tag(
        db, current_user.id, uuid, reassign_entries=reassign_entries
    )
    return {"affected": affected}


@router.post("/tags/{uuid}/empty", status_code=status.HTTP_200_OK)
async def empty_tag(
    uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """Remove all watchlist entries under a tag, keeping the tag. Returns entries removed."""
    removed = await tag_service.empty_tag(db, current_user.id, uuid)
    return {"removed": removed}
