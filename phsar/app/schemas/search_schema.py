from pydantic import BaseModel

from app.schemas.media_schema import MediaUnconnected


class SearchResultDB(BaseModel):
    anime_mal_id: int
    unconnected_media_list: list[MediaUnconnected]
