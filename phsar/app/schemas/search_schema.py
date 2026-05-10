from pydantic import BaseModel, Field

from app.schemas.media_schema import MediaUnconnected


class SearchResultDB(BaseModel):
    anime_mal_id: int
    unconnected_media_list: list[MediaUnconnected]
    # mal_ids the BFS would have traversed but skipped because the media
    # already exists in our catalog under some other anime, reached via a
    # non-crossover relation. Resolved to anime ids in save_service and
    # turned into relation_link merge candidates.
    cross_link_mal_ids: set[int] = Field(default_factory=set)


class SearchResultDBExtended(BaseModel):
   search_result_db_list: list[SearchResultDB]
   unwanted_media: set[tuple[int, str, str]]
