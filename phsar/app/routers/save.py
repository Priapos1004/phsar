from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.users import RoleType
from app.schemas.search_schema import SearchResultDB
from app.services.save_service import save_search_results

router = APIRouter(prefix="/save", tags=["save"])

@router.post("/search-results")
async def save_search_results_endpoint(
    search_results: list[SearchResultDB],
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_roles([RoleType.User.value, RoleType.Admin.value]))
):
    await save_search_results(db, search_results)
    return {"status": "success"}
