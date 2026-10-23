"""Browse pages and their carousels (docs/features/browse.md)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_current_user,
    get_db,
    require_roles,
    require_user_or_admin,
)
from app.models.users import RoleType
from app.schemas.browse_schema import (
    BrowseCarouselOut,
    BrowsePage,
    DiscoverOut,
    DiscoverTodayOut,
)
from app.services import browse_service

router = APIRouter(prefix="/browse", tags=["browse"])
require_admin = require_roles(RoleType.Admin)


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


@router.get("/moods", response_model=DiscoverOut)
async def get_moods(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Discover's moods, and today's once the caller has spun — always, for a guest."""
    return await browse_service.get_discover(db, current_user)


@router.post("/moods/spin", response_model=DiscoverTodayOut)
async def spin_mood(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """Today's mood: the day's first spin draws the caller's next one, later spins
    the same again."""
    return await browse_service.spin(db, current_user)


@router.get("/moods/{mood}", response_model=DiscoverTodayOut)
async def preview_mood(
    mood: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Any mood with its rows, without a spin. Admins only, because the draw is the game —
    a viewer who could open any mood would have no reason to spin."""
    return await browse_service.preview(db, mood)


@router.get("/{page}", response_model=list[BrowseCarouselOut])
async def get_page(
    page: BrowsePage,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """A browse page's carousels, top to bottom, each with the search it runs."""
    return await browse_service.get_page(db, page)
