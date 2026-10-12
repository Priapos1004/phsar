"""Browse pages and their carousels (docs/features/browse.md)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.schemas.browse_schema import BrowseCarouselOut, BrowsePage
from app.services import browse_service

router = APIRouter(prefix="/browse", tags=["browse"])


@router.get("/carousels/{key}", response_model=BrowseCarouselOut)
async def get_carousel(
    key: str,
    on: Annotated[list[str] | None, Query(description="Offered filter sets to switch on.")] = None,
    off: Annotated[list[str] | None, Query(description="Offered filter sets to switch off.")] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """One carousel's search, its filter sets at their defaults except those named."""
    return await browse_service.get_carousel(db, key, on or [], off or [])


@router.get("/{page}", response_model=list[BrowseCarouselOut])
async def get_page(
    page: BrowsePage,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """A browse page's carousels, top to bottom, each with the search it runs."""
    return await browse_service.get_page(db, page)
