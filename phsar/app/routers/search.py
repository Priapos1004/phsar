from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.daos.media_dao import MediaDAO
from app.schemas.search_schema import SearchResultDB
from app.services.search_service import search_mal_api

router = APIRouter(prefix="/search", tags=["search"])

media_dao = MediaDAO()

@router.get("/mal", response_model=list[SearchResultDB])
async def search_mal(query: str, db: AsyncSession = Depends(get_db)):
    existing_mal_ids = await media_dao.get_all_mal_ids(db)
    results = await search_mal_api(query, excluded_mal_ids=set(existing_mal_ids))
    return results
