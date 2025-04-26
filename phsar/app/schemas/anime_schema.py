from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AnimeBase(BaseModel):
    title: str
    name_eng: Optional[str]
    name_jap: Optional[str]
    other_names: list[str] = []
    description: Optional[str]
    cover_image: Optional[str]

class AnimeCreate(AnimeBase):
    pass

class AnimeOut(AnimeBase):
    id: int
    uuid: UUID

    class Config:
        orm_mode = True
