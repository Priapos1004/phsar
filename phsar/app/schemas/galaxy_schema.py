from datetime import datetime
from typing import Annotated, Literal
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
    top_percent: int | None  # its "Top N%" badge


class GalaxyMapOut(BaseModel):
    """The live map (docs/features/galaxy.md)."""
    fitted_at: datetime | None
    sectors: list[GalaxySectorOut]
    regions: list[GalaxyRegionOut]
    stars: list[GalaxyStarOut]


class GalaxySharedOut(BaseModel):
    """One thing a neighbour shares with the anime asked about."""
    kind: Literal["synopsis", "genre", "studio", "source"]
    name: str | None  # the genre, studio or source; none for the synopsis
    chance: float  # how often two anime on the map share it by chance, 0–1


class GalaxyNeighbourOut(GalaxyAnimeOut):
    """A nearby star, with what it shares with the one asked about, rarest first."""
    shared: list[GalaxySharedOut]
