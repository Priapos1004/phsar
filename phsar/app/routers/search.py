from fastapi import APIRouter

from app.schemas.search_schema import SearchResultDB
from app.services.search_service import search_mal_api

router = APIRouter(prefix="/search", tags=["search"])

@router.get("/mal", response_model=list[SearchResultDB])
async def search_mal(query: str):
    results = await search_mal_api(query)
    return results
