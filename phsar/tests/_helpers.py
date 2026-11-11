"""Shared test helpers across services/, routers/, daos/.

`media_kwargs` filled out four times in test files because every test that
touches a Media row has to populate the same NOT-NULL columns. This is the
canonical version; new tests should import it instead of redeclaring.
"""

import json
from typing import Any, NamedTuple

from sqlalchemy import select

from app.models.anime_search import AnimeSearch
from app.models.media import MediaType, RelationType, SeasonType
from app.models.users import RoleType, Users


class SentinelSeason(NamedTuple):
    """A season that scopes a search response to one fixture's rows.

    Under `PHSAR_TEST_DB=dev` a search hits whatever the developer's catalogue holds,
    while the suite's own database is empty. That asymmetry is what makes a search
    assertion vacuous: sized or positioned against an unknown row set, it has to
    hedge, and the hedge passes on the empty list the suite's own database produces.

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


def genres_param(*groups: dict, mode: str = "all") -> str:
    """The search's `genres` query param: `groups` joined by `mode`."""
    return json.dumps({"mode": mode, "groups": list(groups)})


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


async def default_tag_uuid(client, headers) -> str:
    """The caller's default watchlist list, which every non-restricted user has — the
    one a test files an entry under when the list itself isn't the point."""
    tags = (await client.get("/watchlist/tags", headers=headers)).json()
    return next(t["uuid"] for t in tags if t["is_default"])


async def rate_media(
    client, headers, media_uuid, status: str = "completed", rating: float = 8.0, note: str | None = None,
) -> None:
    """Rate one media as the caller, through the real endpoint."""
    resp = await client.put(
        f"/ratings/media/{media_uuid}", json={"rating": rating, "watch_status": status, "note": note},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def list_media(client, headers, *media_uuids) -> None:
    """Put each media on the caller's default watchlist list, through the real endpoint."""
    tag_uuid = await default_tag_uuid(client, headers)
    for media_uuid in media_uuids:
        resp = await client.put(f"/watchlist/media/{media_uuid}", json={"tag_uuid": tag_uuid}, headers=headers)
        assert resp.status_code == 200, resp.text


async def make_user(db, username: str = "testuser", role: RoleType = RoleType.User) -> Users:
    """Insert and flush a Users row (the inline `Users(...)` pattern repeated across
    the service tests). Password hash is a placeholder — auth isn't exercised here."""
    user = Users(username=username, hashed_password="x", role=role)
    db.add(user)
    await db.flush()
    return user


def split_cluster(
    anchor_mal_id: int,
    member_mal_ids: list[int],
    bridge_edges: list[list] | None = None,
) -> dict:
    """One entry of `SplitCandidate.clusters` — the JSONB DisjointFranchise dict
    that `find_disjoint_franchises` emits and `execute_split` reads back.

    Here rather than inline, because the router and service tests both build one:
    two hand-written copies of a four-key schema means adding a key leaves one
    side silently asserting the old shape.

    Defaults `substance_member_mal_ids` to every member — the substance gate is
    exercised in test_relation_classifier.py, not by the consumers of this.
    """
    return {
        "member_mal_ids": member_mal_ids,
        "substance_member_mal_ids": member_mal_ids,
        "suggested_anchor_mal_id": anchor_mal_id,
        "bridge_edges": bridge_edges if bridge_edges is not None else [],
    }


class NoopProgressReporter:
    """Stands in for `ProgressReporter` in a dispatcher test: the real one opens its own
    short-lived sessions, which would write outside the test's transaction."""

    def __init__(self, *_args, **_kwargs):
        pass

    async def update(self, *_args, **_kwargs):
        return None


def fake_job(payload: dict | None = None, job_id: int = 12345):
    """A stand-in `Job` for a dispatcher called directly: its id and payload are all one reads."""
    return type("FakeJob", (), {"id": job_id, "payload": payload or {}})()


async def probe_row(db) -> AnimeSearch:
    """The row `embeddings_are_stale` re-encodes: the lowest-id anime's."""
    return (await db.execute(select(AnimeSearch).order_by(AnimeSearch.anime_id).limit(1))).scalar_one()


def fake_galaxy_fit(anime, _media, _previous) -> dict[str, Any]:
    """A stand-in for `galaxy_compute.fit`: one sector holding one region and every anime,
    enough for the swap to write. `test_galaxy_compute` holds it to the real fit's shape."""
    ids = [a.anime_id for a in anime]
    return {
        "stars": [
            {"anime_id": aid, "x": 0.0, "y": 0.0, "z10": [0.0] * 10, "sector": 0, "region": 0,
             "between": False, "trained": True, "features": [1.0, 0.0], "uncertainty": 0.0}
            for aid in ids
        ],
        "groups": [
            {"level": "sector", "number": 0, "parent": None, "auto_name": "Auto sector", "x": 0.0, "y": 0.0,
             "trained_members": ids},
            {"level": "region", "number": 0, "parent": 0, "auto_name": "Auto region", "x": 0.0, "y": 0.0,
             "trained_members": ids},
        ],
        "blob": b"models",
        "pair_cosine_percentiles": [0.0] * 101,
        "summary": {"trained": len(ids), "predicted": 0, "sectors": 1, "regions": 1, "between_share": 0.0},
    }
