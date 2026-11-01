from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


class GalaxyGroupRename(BaseModel):
    # None or blank clears the hand name, so the group shows its auto name again.
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None


class GalaxyGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    name: str | None
    auto_name: str


class GalaxySectorOut(BaseModel):
    uuid: UUID
    number: int
    name: str
    x: float
    y: float


class GalaxyRegionOut(GalaxySectorOut):
    sector: int  # its sector's `number`


class GalaxyAnimeOut(BaseModel):
    """An anime as the map shows it: enough for a hover card and the link to its page."""
    anime_uuid: UUID
    title: str
    name_eng: str | None
    name_jap: str | None
    cover_image: str | None
    score: float | None  # the anime's MAL score, as its card shows it
    year: int | None  # its main story's first season year


class GalaxyStarOut(GalaxyAnimeOut):
    x: float
    y: float
    sector: int
    region: int
    between: bool
    trained: bool
    genres: list[str]  # the genres a majority of its media carry


class GalaxyMapOut(BaseModel):
    """The live map (docs/features/galaxy.md)."""
    fitted_at: datetime | None
    sectors: list[GalaxySectorOut]
    regions: list[GalaxyRegionOut]
    stars: list[GalaxyStarOut]


class GalaxyNeighbourOut(GalaxyAnimeOut):
    """A nearby star, with what it shares with the one asked about."""
    shared_genres: list[str]
    shared_studios: list[str]
    shared_source: str | None  # the main story's usual source, when both have the same one
    # How alike the two synopses are, as a percentile of random pairs on the map: 90 means
    # closer than nine in ten.
    synopsis_percentile: int
