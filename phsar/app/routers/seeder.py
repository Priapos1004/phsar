from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.users import RoleType
from app.seeders.media_seeder import seed_popular_anime

router = APIRouter(prefix="/seed", tags=["seeder"])

@router.post("/media")
async def seed_media(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_roles(RoleType.Admin)),
):
    await seed_popular_anime(db)
    return {"status": "success", "message": "Media seeding completed."}
