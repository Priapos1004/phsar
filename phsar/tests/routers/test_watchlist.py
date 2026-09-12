"""Watchlist router — tag + entry endpoints (v0.15.0)."""

import pytest

from app.models.anime import Anime
from app.models.media import Media, RelationType, SeasonType
from app.models.ratings import Ratings, WatchStatus
from tests._helpers import make_user, media_kwargs


# NEGATIVE mal_ids so fixtures can't collide with the dev DB's real catalog on the
# globally-unique media.mal_id (real MAL ids are always positive) — the suite-wide
# convention documented in tests/seeders/test_relation_backfiller.py.
@pytest.fixture
async def test_media(db_session):
    anime = Anime(mal_id=-61000, title="WL Test Anime")
    db_session.add(anime)
    await db_session.flush()
    media = Media(**media_kwargs(anime.id, -61001, title="WL Test Media"))
    db_session.add(media)
    await db_session.flush()
    return media


@pytest.fixture
async def test_media_list(db_session):
    anime = Anime(mal_id=-62000, title="WL Bulk Anime")
    db_session.add(anime)
    await db_session.flush()
    media = [Media(**media_kwargs(anime.id, -62001 - i, title=f"WL Bulk {i}")) for i in range(3)]
    db_session.add_all(media)
    await db_session.flush()
    return media


async def _default_tag_uuid(client, headers) -> str:
    tags = (await client.get("/watchlist/tags", headers=headers)).json()
    return next(t["uuid"] for t in tags if t["is_default"])


async def test_registered_user_has_default_tag(client, user_auth_headers):
    """Registration seeds the immutable default tag, so a fresh user already
    has exactly one tag and it's the default."""
    resp = await client.get("/watchlist/tags", headers=user_auth_headers)
    assert resp.status_code == 200
    tags = resp.json()
    assert len(tags) == 1
    assert tags[0]["is_default"] is True
    assert tags[0]["name"] == "Watchlist"
    assert tags[0]["entry_count"] == 0
    assert tags[0]["anime_count"] == 0


async def test_restricted_user_cannot_access_tags(client, restricted_user_auth_headers):
    resp = await client.get("/watchlist/tags", headers=restricted_user_auth_headers)
    assert resp.status_code == 403


async def test_create_and_list_tag(client, user_auth_headers):
    resp = await client.post(
        "/watchlist/tags", json={"name": "Films", "color": "#123ABC"}, headers=user_auth_headers
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["name"] == "Films"
    assert created["color"] == "#123abc"  # normalized
    assert created["is_default"] is False

    listing = (await client.get("/watchlist/tags", headers=user_auth_headers)).json()
    assert [t["name"] for t in listing] == ["Watchlist", "Films"]  # default first


async def test_create_duplicate_tag_name_conflicts(client, user_auth_headers):
    await client.post(
        "/watchlist/tags", json={"name": "Dup", "color": "#000000"}, headers=user_auth_headers
    )
    resp = await client.post(
        "/watchlist/tags", json={"name": "Dup", "color": "#ffffff"}, headers=user_auth_headers
    )
    assert resp.status_code == 409


async def test_invalid_color_rejected(client, user_auth_headers):
    resp = await client.post(
        "/watchlist/tags", json={"name": "Bad", "color": "red"}, headers=user_auth_headers
    )
    assert resp.status_code == 422


async def test_default_tag_cannot_be_renamed_or_deleted(client, user_auth_headers):
    default = (await client.get("/watchlist/tags", headers=user_auth_headers)).json()[0]
    uuid = default["uuid"]

    patch = await client.patch(
        f"/watchlist/tags/{uuid}", json={"name": "Nope"}, headers=user_auth_headers
    )
    assert patch.status_code == 403

    delete = await client.delete(f"/watchlist/tags/{uuid}", headers=user_auth_headers)
    assert delete.status_code == 403


async def test_update_and_delete_custom_tag(client, user_auth_headers):
    created = (await client.post(
        "/watchlist/tags", json={"name": "Temp", "color": "#000000"}, headers=user_auth_headers
    )).json()
    uuid = created["uuid"]

    patched = await client.patch(
        f"/watchlist/tags/{uuid}", json={"color": "#ABCDEF"}, headers=user_auth_headers
    )
    assert patched.status_code == 200
    assert patched.json()["color"] == "#abcdef"

    deleted = await client.delete(f"/watchlist/tags/{uuid}", headers=user_auth_headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"affected": 0}

    remaining = (await client.get("/watchlist/tags", headers=user_auth_headers)).json()
    assert [t["name"] for t in remaining] == ["Watchlist"]


async def test_empty_endpoint_on_default_tag(client, user_auth_headers):
    """The default tag exposes empty (not delete); with no entries it removes 0."""
    default = (await client.get("/watchlist/tags", headers=user_auth_headers)).json()[0]
    resp = await client.post(
        f"/watchlist/tags/{default['uuid']}/empty", headers=user_auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"removed": 0}


# --- Entries ---

async def test_upsert_entry_and_media_tags(client, user_auth_headers, test_media):
    tag_uuid = await _default_tag_uuid(client, user_auth_headers)
    resp = await client.put(
        f"/watchlist/media/{test_media.uuid}",
        json={"tag_uuid": tag_uuid, "priority": 1, "note": "soon"},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["priority"] == 1
    assert data["note"] == "soon"
    assert data["tag"]["uuid"] == tag_uuid
    assert data["media_uuid"] == str(test_media.uuid)

    tags = (await client.get("/watchlist/media-tags", headers=user_auth_headers)).json()
    assert len(tags["entries"]) == 1
    entry = tags["entries"][0]
    assert entry["media_uuid"] == str(test_media.uuid)
    assert entry["anime_uuid"]  # anime-level color aggregation source
    assert entry["tag_uuid"] == tag_uuid
    assert entry["tag_name"] == "Watchlist"
    assert entry["tag_color"]  # colored bookmark source

    items = (await client.get("/watchlist/items", headers=user_auth_headers)).json()
    assert len(items) == 1
    assert items[0]["tag_name"] == "Watchlist"


async def test_upsert_defaults_priority(client, user_auth_headers, test_media):
    tag_uuid = await _default_tag_uuid(client, user_auth_headers)
    resp = await client.put(
        f"/watchlist/media/{test_media.uuid}",
        json={"tag_uuid": tag_uuid},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["priority"] == 3


async def test_delete_entry(client, user_auth_headers, test_media):
    tag_uuid = await _default_tag_uuid(client, user_auth_headers)
    await client.put(
        f"/watchlist/media/{test_media.uuid}",
        json={"tag_uuid": tag_uuid}, headers=user_auth_headers,
    )
    deleted = await client.delete(f"/watchlist/media/{test_media.uuid}", headers=user_auth_headers)
    assert deleted.status_code == 204
    tags = (await client.get("/watchlist/media-tags", headers=user_auth_headers)).json()
    assert tags["entries"] == []


async def test_bulk_upsert_note_on_first_main(client, user_auth_headers, db_session):
    """Bulk note lands on the chronologically-first main media only; priority applies to
    all. Invariant to request order (scrambled submission)."""
    anime = Anime(mal_id=-63000, title="WL Mixed Anime")
    db_session.add(anime)
    await db_session.flush()
    winner = Media(**media_kwargs(
        anime.id, -63001, title="Earliest Main",
        relation_type=RelationType.Main, anime_season_name=SeasonType.Winter, anime_season_year=2020,
    ))
    later_main = Media(**media_kwargs(
        anime.id, -63002, title="Later Main",
        relation_type=RelationType.Main, anime_season_name=SeasonType.Spring, anime_season_year=2022,
    ))
    earlier_side = Media(**media_kwargs(
        anime.id, -63003, title="Earlier Side",
        relation_type=RelationType.SideStory, anime_season_name=SeasonType.Fall, anime_season_year=2019,
    ))
    db_session.add_all([winner, later_main, earlier_side])
    await db_session.flush()

    tag_uuid = await _default_tag_uuid(client, user_auth_headers)
    resp = await client.put(
        "/watchlist/bulk",
        json={
            "media_uuids": [str(m.uuid) for m in (later_main, earlier_side, winner)],
            "tag_uuid": tag_uuid,
            "priority": 2,
            "note": "start here",
        },
        headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert len(out) == 3
    assert all(o["priority"] == 2 for o in out)
    by_uuid = {o["media_uuid"]: o for o in out}
    assert by_uuid[str(winner.uuid)]["note"] == "start here"
    assert by_uuid[str(later_main.uuid)]["note"] is None
    assert by_uuid[str(earlier_side.uuid)]["note"] is None


async def test_bulk_delete_entries(client, user_auth_headers, test_media_list):
    tag_uuid = await _default_tag_uuid(client, user_auth_headers)
    await client.put(
        "/watchlist/bulk",
        json={"media_uuids": [str(m.uuid) for m in test_media_list], "tag_uuid": tag_uuid},
        headers=user_auth_headers,
    )
    resp = await client.post(
        "/watchlist/bulk-delete",
        json={"media_uuids": [str(test_media_list[0].uuid), str(test_media_list[1].uuid)]},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2}


async def test_restricted_user_cannot_upsert_entry(client, restricted_user_auth_headers, test_media):
    resp = await client.put(
        f"/watchlist/media/{test_media.uuid}",
        json={"tag_uuid": "00000000-0000-0000-0000-000000000000"},
        headers=restricted_user_auth_headers,
    )
    assert resp.status_code == 403


# --- Readiness inputs on /watchlist/items ---
#
# The readiness verdict itself is computed client-side; what the backend owes it is a
# set of per-entry columns plus one per-anime pair. The per-entry ones are trivially
# correct. The pair — `franchise_airing` / `franchise_upcoming_key` — is the only part
# of this projection that reads media OUTSIDE the user's watchlist, which is why it
# carries the tests: a regression there is invisible in the entry rows, and the filter
# would silently stop blocking franchises with an unlisted sequel on the way.


@pytest.fixture
async def listed(db_session):
    """One anime's watchlistable finished media. The rest of the franchise gets added
    per-test, so each test states the shape it is asserting about."""
    anime = Anime(mal_id=-64000, title="WL Readiness Anime")
    db_session.add(anime)
    await db_session.flush()
    media = Media(**media_kwargs(anime.id, -64001, title="Listed S1"))
    db_session.add(media)
    await db_session.flush()
    return media


async def _watchlist_items(client, headers, media, db_session):
    """Watchlist `media`, then return the single /watchlist/items row for it."""
    await db_session.flush()
    tag_uuid = await _default_tag_uuid(client, headers)
    resp = await client.put(
        f"/watchlist/media/{media.uuid}", json={"tag_uuid": tag_uuid}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    items = (await client.get("/watchlist/items", headers=headers)).json()
    mine = [i for i in items if i["media_uuid"] == str(media.uuid)]
    assert len(mine) == 1, f"expected exactly one row, got {len(mine)}"
    return mine[0]


async def test_items_carry_readiness_inputs(client, user_auth_headers, listed, db_session):
    """A lone finished media: nothing rated, nothing else in the franchise."""
    item = await _watchlist_items(client, user_auth_headers, listed, db_session)
    assert item["airing_status"] == "Finished Airing"
    assert item["watch_status"] is None
    assert item["franchise_airing"] is False
    assert item["franchise_upcoming_key"] is None


@pytest.mark.parametrize(
    ("relation", "status", "blocks"),
    [
        # The whole point of the franchise columns: the airing sequel is NOT on the
        # watchlist, so no entry row could carry its status — yet starting S1 now
        # still means catching up and then waiting.
        pytest.param(RelationType.Main, None, True, id="unlisted-main-blocks"),
        # An airing OVA is not a season you wait for, so it can't park the franchise.
        pytest.param(RelationType.SideStory, None, False, id="side-content-never-blocks"),
        # Dropped it → you are not waiting for it. The asymmetry with an ON-list
        # airing media, which blocks whatever you rated it.
        pytest.param(RelationType.Main, WatchStatus.dropped, False, id="dropped-exempts"),
        # ...and `dropped` is the ONLY status that exempts: pausing a season is not
        # quitting it. Guards against an `IS NOT NULL` shortcut on watch_status.
        pytest.param(RelationType.Main, WatchStatus.on_hold, True, id="on-hold-still-blocks"),
    ],
)
async def test_franchise_airing_over_media_outside_the_watchlist(
    client, user_auth_headers, listed, db_session, relation, status, blocks
):
    airing = Media(**media_kwargs(
        listed.anime_id, -64002, title="Unlisted S2",
        airing_status="Currently Airing", relation_type=relation,
    ))
    db_session.add(airing)
    await db_session.flush()
    if status is not None:
        # Through the API, so the assertion reads a row the rating path actually
        # wrote. Legal here because the media is airing, not unaired.
        resp = await client.put(
            f"/ratings/media/{airing.uuid}",
            json={"rating": 7.0, "watch_status": status.value},
            headers=user_auth_headers,
        )
        assert resp.status_code in (200, 201), resp.text

    item = await _watchlist_items(client, user_auth_headers, listed, db_session)
    assert item["franchise_airing"] is blocks


async def test_anime_with_no_main_story_reports_not_blocked(client, user_auth_headers, db_session):
    """Watchlist a side story in an anime that has no main story at all, and the
    franchise subquery produces no row for it — a LEFT JOIN miss, not a False.

    Absent evidence of upcoming content nothing blocks, so the COALESCE has to turn
    that into False in SQL: `WatchlistItem.franchise_airing` is a non-optional `bool`,
    and a NULL would fail validation and 500 the whole page rather than this one
    entry. The classifier leaves no such anime today, but nothing forbids one."""
    anime = Anime(mal_id=-64100, title="WL Side-Only Anime")
    db_session.add(anime)
    await db_session.flush()
    side = Media(**media_kwargs(
        anime.id, -64101, title="Side Only", relation_type=RelationType.SideStory,
    ))
    db_session.add(side)
    await db_session.flush()

    item = await _watchlist_items(client, user_auth_headers, side, db_session)
    assert item["franchise_airing"] is False
    assert item["franchise_upcoming_key"] is None


async def test_franchise_upcoming_key_takes_the_earliest_announced_season(
    client, user_auth_headers, listed, db_session
):
    """`year * 10 + season rank`, minimised across the franchise, so the client
    compares one integer against the key it builds for next season.

    The encoding is shared across a Python/TypeScript boundary, so no import can check
    it. This literal pins the backend half; the frontend's key builder has to pin the
    same number against the same season, and nothing but these two tests holds them
    together.

    An undated announcement contributes nothing — it is not a season you can plan
    around, and the `else_`-free CASE drops it rather than ranking it ahead of
    Winter."""
    db_session.add_all([
        Media(**media_kwargs(
            listed.anime_id, -64006, title="Winter 2027 S3", airing_status="Not yet aired",
            anime_season_name=SeasonType.Winter, anime_season_year=2027,
        )),
        Media(**media_kwargs(
            listed.anime_id, -64007, title="Fall 2026 S2", airing_status="Not yet aired",
            anime_season_name=SeasonType.Fall, anime_season_year=2026,
        )),
        Media(**media_kwargs(
            listed.anime_id, -64008, title="Undated S4", airing_status="Not yet aired",
        )),
    ])
    item = await _watchlist_items(client, user_auth_headers, listed, db_session)
    assert item["franchise_upcoming_key"] == 2026 * 10 + 4  # Fall 2026, not Winter 2027


async def test_watch_status_is_the_callers_own(client, user_auth_headers, listed, db_session):
    """The ratings LEFT JOIN is scoped to the caller. Without the user_id predicate it
    would both leak the other user's status AND fan one entry into a row per rater —
    so the row-count assertion in `_watchlist_items` is half of what this covers.

    The other user's rating is written directly: registering a second API user to
    place one row costs more than it proves."""
    other = await make_user(db_session, username="wl_other_rater")
    db_session.add(Ratings(
        user_id=other.id, media_id=listed.id, rating=7.0, watch_status=WatchStatus.completed,
    ))
    await db_session.flush()

    item = await _watchlist_items(client, user_auth_headers, listed, db_session)
    assert item["watch_status"] is None

    resp = await client.put(
        f"/ratings/media/{listed.uuid}",
        json={"rating": 7.0, "watch_status": WatchStatus.on_hold.value},
        headers=user_auth_headers,
    )
    assert resp.status_code in (200, 201), resp.text
    items = (await client.get("/watchlist/items", headers=user_auth_headers)).json()
    mine = [i for i in items if i["media_uuid"] == str(listed.uuid)]
    assert len(mine) == 1
    assert mine[0]["watch_status"] == "on_hold"
