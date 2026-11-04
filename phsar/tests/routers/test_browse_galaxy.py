"""GET /browse/galaxy and /browse/galaxy/{uuid}/neighbours over a hand-made map: what the
map serves for its groups and stars, and the neighbours' order and reasons. The map is
installed through `GalaxyDAO.replace_fit`, which inside the test's transaction replaces
whatever map the database holds."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.daos.galaxy_dao import GalaxyDAO
from app.models.anime import Anime
from app.models.genre import Genre
from app.models.media import Media, OriginalSource, SeasonType
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from app.services.anime_search_service import anime_title_texts
from app.services.vector_embedding_service import create_anime_embedding
from tests._helpers import media_kwargs

_SWORD = "A swordsman hunts demons across a burning empire and keeps a promise to his sister."
# title → (synopsis, genres, studio, source, MAL score, year, region, position in feature space)
_ANIME = {
    "Gx Target": (_SWORD, ("Action", "Fantasy"), "Gx Studio A", OriginalSource.Manga, 8.0, 2019, 0, (0.0, 0.0)),
    "Gx Twin": (_SWORD, ("Action", "Fantasy"), "Gx Studio A", OriginalSource.Manga, 7.0, 2021, 0, (1.0, 0.0)),
    "Gx Middle": (
        "Two friends open a bakery by the sea.", ("Action",), "Gx Studio B", OriginalSource.Original, 6.5, 2010, 1,
        (0.0, 3.0),
    ),
    "Gx Far": ("Accountants audit tax filings.", ("Comedy",), "Gx Studio B", OriginalSource.Novel, None, None, 1, (9.0, 9.0)),
}
# Far-off stars sharing nothing with the target, so that on this map of eight, a trait two
# anime carry is rare enough to be a neighbour's reason and one three carry is not.
_FILLERS = {
    f"Gx Filler {i}": (synopsis, (), "Gx Studio B", OriginalSource.Original, None, None, 1, (20.0 + i, 20.0))
    for i, synopsis in enumerate([
        "A lighthouse keeper logs passing ships.",
        "Retirees restore a vintage tram.",
        "A florist learns sign language.",
        "Two chess clubs share one room.",
    ])
}
_ANIME |= _FILLERS
# Synopsis similarities of random pairs, spread evenly over the range e5 gives.
_PERCENTILES = [0.7 + 0.003 * i for i in range(101)]


@pytest.fixture
async def galaxy(db_session) -> dict[str, Anime]:
    genres = {g.name: g.id for g in (await db_session.execute(select(Genre))).scalars()}
    studios = {}
    for name in ("Gx Studio A", "Gx Studio B"):
        studios[name] = Studio(name=name)
        db_session.add(studios[name])
    anime = {}
    for i, (title, (synopsis, tags, studio, source, score, year, _, _)) in enumerate(_ANIME.items()):
        a = Anime(mal_id=-95100 - i, title=title, description=synopsis, cover_image=f"https://example/{i}.webp")
        db_session.add(a)
        await db_session.flush()
        season = {"anime_season_name": SeasonType.Spring, "anime_season_year": year} if year else {}
        media = Media(**media_kwargs(
            a.id, -95100 - i, title=title, description=synopsis, original_source=source,
            score=score, scored_by=1000 if score else 0, **season,
        ))
        db_session.add(media)
        await db_session.flush()
        db_session.add_all([MediaGenre(media_id=media.id, genre_id=genres[t]) for t in tags])
        db_session.add(MediaStudio(media_id=media.id, studio_id=studios[studio].id))
        await create_anime_embedding(
            db_session, anime_id=a.id, title_texts=anime_title_texts(a), description_text=synopsis,
        )
        anime[title] = a
    await db_session.flush()
    await GalaxyDAO().replace_fit(
        db_session, blob=b"", params={"pair_cosine_percentiles": _PERCENTILES},
        groups=[
            {"level": "sector", "number": 0, "parent": None, "auto_name": "Auto sector", "x": 0.5, "y": 1.5},
            {"level": "region", "number": 0, "parent": 0, "auto_name": "Auto blades", "x": 0.5, "y": 0.0},
            {"level": "region", "number": 1, "parent": 0, "auto_name": "Auto bakeries", "x": 4.5, "y": 6.0},
        ],
        names={0: "Sword Sector"},
        stars=[
            {
                "anime_id": anime[title].id, "x": pos[0], "y": pos[1], "z10": [0.0] * 10, "features": list(pos),
                "sector": 0, "region": region, "between": title == "Gx Far", "trained": score is not None,
            }
            for title, (_, _, _, _, score, _, region, pos) in _ANIME.items()
        ],
    )
    await db_session.flush()
    return anime


async def test_the_map_serves_its_groups_and_stars(client, restricted_user_auth_headers, galaxy):
    """Guests see the map too; `/browse/galaxy` reaches its own route, not `/{page}`'s."""
    res = await client.get("/browse/galaxy", headers=restricted_user_auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fitted_at"] is not None
    assert [(g["number"], g["name"]) for g in body["sectors"]] == [(0, "Sword Sector")]
    assert [(g["number"], g["sector"], g["name"]) for g in body["regions"]] == [
        (0, 0, "Auto blades"), (1, 0, "Auto bakeries"),
    ]
    stars = {s["title"]: s for s in body["stars"]}
    assert set(stars) == set(_ANIME)
    target = stars["Gx Target"]
    assert target["anime_uuid"] == str(galaxy["Gx Target"].uuid)
    assert (target["score"], target["year"], target["genres"]) == (8.0, 2019, ["Action", "Fantasy"])
    assert (target["sector"], target["region"], target["between"], target["trained"]) == (0, 0, False, True)
    far = stars["Gx Far"]
    assert (far["score"], far["year"], far["region"], far["between"], far["trained"]) == (None, None, 1, True, False)
    # The search's "Top N%", ranked over the whole catalogue, so only the order is the fixture's.
    assert target["top_percent"] < stars["Gx Twin"]["top_percent"] < stars["Gx Middle"]["top_percent"]
    assert far["top_percent"] is None


async def test_neighbours_come_nearest_first_with_what_they_share(client, user_auth_headers, galaxy):
    res = await client.get(f"/browse/galaxy/{galaxy['Gx Target'].uuid}/neighbours", headers=user_auth_headers)
    assert res.status_code == 200, res.text
    near = res.json()
    assert [n["title"] for n in near] == ["Gx Twin", "Gx Middle", "Gx Far", *_FILLERS]
    twin, middle = near[:2]

    def shared(n):
        return [(s["kind"], s["name"]) for s in n["shared"]]

    # Rarest first: the same synopsis under another title is closer than nine random pairs in
    # ten, ahead of the traits two of the eight carry, tied and ordered by kind. Action, which
    # three carry, is too common to count.
    assert shared(twin) == [("synopsis", None), ("genre", "Fantasy"), ("source", "Manga"), ("studio", "Gx Studio A")]
    assert twin["shared"][0]["chance"] < 0.1
    assert [s["chance"] for s in twin["shared"][1:]] == [0.25, 0.25, 0.25]
    assert ("genre", "Action") not in shared(middle)


async def test_an_anime_without_a_star_has_no_neighbours(client, user_auth_headers, galaxy):
    res = await client.get(f"/browse/galaxy/{uuid4()}/neighbours", headers=user_auth_headers)
    assert res.status_code == 404
