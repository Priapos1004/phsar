"""Browse pages and their carousels (docs/features/browse.md)."""

from typing import Annotated
from uuid import UUID

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
from app.schemas.galaxy_schema import GalaxyMapOut, GalaxyNeighbourOut
from app.services import browse_service, galaxy_service

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


# Above `/{page}`, which would otherwise take "galaxy" for a page name.
@router.get("/galaxy", response_model=GalaxyMapOut)
async def get_galaxy(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The galaxy map: every anime's star, and the sectors and regions they fall in."""
    return await galaxy_service.get_map(db)


@router.get("/galaxy/{anime_uuid}/neighbours", response_model=list[GalaxyNeighbourOut])
async def get_galaxy_neighbours(
    anime_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The stars nearest one anime's, with what each shares with it."""
    return await galaxy_service.neighbours(db, anime_uuid)


@router.get("/{page}", response_model=list[BrowseCarouselOut])
async def get_page(
    page: BrowsePage,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """A browse page's carousels, top to bottom, each with the search it runs."""
    return await browse_service.get_page(db, page)
