"""Shared test helpers across services/, routers/, daos/.

`media_kwargs` filled out four times in test files because every test that
touches a Media row has to populate the same NOT-NULL columns. This is the
canonical version; new tests should import it instead of redeclaring.
"""

from typing import NamedTuple

from app.models.media import MediaType, RelationType, SeasonType
from app.models.users import RoleType, Users


class SentinelSeason(NamedTuple):
    """A season that scopes a search response to one fixture's rows.

    Router tests run against the real `DATABASE_URL`, so a search hits whatever
    the developer's catalogue holds while CI's is empty. That asymmetry is what
    makes a search assertion vacuous: sized or positioned against an unknown row
    set, it has to hedge, and the hedge passes on the empty list CI produces.

    Stamp the fixture's media with `season.columns` and pass `season.filter` as
    the request's `anime_season`, and the response is the fixture's rows in both
    places. Both are derived, so a stamped season cannot drift from the filtered
    one and silently un-scope the query. Pick any year the catalogue can't
    contain — MAL has nothing before the 1910s, and the column's own constraint
    floors it at 1900. Any two modules may share a year: a test builds only its
    own fixture, so their rows never meet in one response.
    """

    year: int
    name: SeasonType = SeasonType.Winter

    @property
    def filter(self) -> str:
        return f"{self.name.value} {self.year}"

    @property
    def columns(self) -> dict:
        return {"anime_season_name": self.name, "anime_season_year": self.year}


def media_kwargs(anime_id: int, mal_id: int, **overrides) -> dict:
    """Return a dict suitable for `Media(**...)` with all NOT-NULL columns
    populated. Pass keyword overrides to customize specific fields."""
    base = {
        "anime_id": anime_id,
        "mal_id": mal_id,
        "mal_url": f"https://example/{mal_id}",
        "title": f"M{mal_id}",
        "media_type": MediaType.TV,
        "relation_type": RelationType.Main,
        "scored_by": 0,
        "airing_status": "Finished Airing",
    }
    base.update(overrides)
    return base


async def make_user(db, username: str = "testuser", role: RoleType = RoleType.User) -> Users:
    """Insert and flush a Users row (the inline `Users(...)` pattern repeated across
    the service tests). Password hash is a placeholder — auth isn't exercised here."""
    user = Users(username=username, hashed_password="x", role=role)
    db.add(user)
    await db.flush()
    return user
