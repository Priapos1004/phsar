from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_user_or_admin
from app.schemas import tag_schema, watchlist_schema
from app.services import tag_service, watchlist_service

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


# --- Entries ---

@router.get("/items", response_model=list[watchlist_schema.WatchlistItem])
async def get_watchlist_items(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """All of the user's watchlist entries in a wide shape — the overview page's
    single fetch (list + grid derived client-side)."""
    return await watchlist_service.get_watchlist_items(db, current_user.id)


@router.get("/media-ids", response_model=watchlist_schema.WatchlistMediaIds)
async def get_watchlisted_media_ids(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """The set of watchlisted media UUIDs — drives the bookmark icon states."""
    return await watchlist_service.get_watchlisted_media_uuids(db, current_user.id)


@router.put("/media/{media_uuid}", response_model=watchlist_schema.WatchlistOut)
async def upsert_watchlist(
    media_uuid: UUID,
    data: watchlist_schema.WatchlistCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """Create or update the watchlist entry for a media (priority + tag + note)."""
    return await watchlist_service.upsert_watchlist(db, current_user.id, media_uuid, data)


@router.get("/media/{media_uuid}", response_model=watchlist_schema.WatchlistOut)
async def get_watchlist_for_media(
    media_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    return await watchlist_service.get_watchlist_for_media(db, current_user.id, media_uuid)


@router.delete("/media/{media_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(
    media_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    await watchlist_service.delete_watchlist(db, current_user.id, media_uuid)


@router.get("/anime/{anime_uuid}", response_model=list[watchlist_schema.WatchlistOut])
async def get_watchlist_for_anime(
    anime_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    return await watchlist_service.get_watchlist_for_anime(db, current_user.id, anime_uuid)


@router.put("/bulk", response_model=list[watchlist_schema.WatchlistOut])
async def bulk_upsert_watchlist(
    data: watchlist_schema.WatchlistBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """Add/update watchlist entries for multiple media at once (note applies to all)."""
    return await watchlist_service.bulk_upsert_watchlist(db, current_user.id, data)


@router.post("/bulk-delete", status_code=status.HTTP_200_OK)
async def bulk_delete_watchlist(
    data: watchlist_schema.WatchlistBulkDelete,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """Remove watchlist entries for multiple media at once. Returns the count removed."""
    count = await watchlist_service.bulk_delete_watchlist(db, current_user.id, data.media_uuids)
    return {"deleted": count}
