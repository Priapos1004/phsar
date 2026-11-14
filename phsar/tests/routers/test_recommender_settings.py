"""The recommender's settings and the history start they read: docs/features/recommender.md."""

from app.models.anime import Anime
from app.models.media import Media
from tests._helpers import media_kwargs, rate_media


async def _rated(client, headers, db_session, mal_id: int) -> str:
    """A fresh one-media anime rated by the caller: its rating's uuid."""
    anime = Anime(mal_id=mal_id, title=f"HistoryStart{mal_id}")
    db_session.add(anime)
    await db_session.flush()
    media = Media(**media_kwargs(anime.id, mal_id))
    db_session.add(media)
    await db_session.flush()
    return await rate_media(client, headers, media.uuid)


async def _choose(client, headers, rating: str | None):
    return await client.put("/ratings/history-start", json={"rating": rating}, headers=headers)


async def _chosen(client, headers) -> str | None:
    resp = await client.get("/ratings/history-start", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["chosen"]


async def test_hot_anime_are_recommended_unless_turned_off(client, user_auth_headers):
    assert (await client.get("/users/settings", headers=user_auth_headers)).json()["recommend_hot"] is True
    resp = await client.put("/users/settings", json={"recommend_hot": False}, headers=user_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["recommend_hot"] is False


async def test_the_history_start_detects_until_a_rating_is_chosen(client, user_auth_headers, db_session):
    rating = await _rated(client, user_auth_headers, db_session, -94001)
    assert await _chosen(client, user_auth_headers) is None
    resp = await _choose(client, user_auth_headers, rating)
    assert resp.status_code == 200, resp.text
    assert resp.json()["chosen"] == rating
    assert await _chosen(client, user_auth_headers) == rating
    assert (await _choose(client, user_auth_headers, None)).json()["chosen"] is None


async def test_the_history_starts_only_at_the_callers_own_rating(client, user_auth_headers, admin_auth_headers, db_session):
    theirs = await _rated(client, admin_auth_headers, db_session, -94002)
    assert (await _choose(client, user_auth_headers, theirs)).status_code == 404
    assert await _chosen(client, user_auth_headers) is None


async def test_deleting_the_chosen_rating_returns_the_start_to_detected(client, user_auth_headers, db_session):
    rating = await _rated(client, user_auth_headers, db_session, -94003)
    await _choose(client, user_auth_headers, rating)
    assert (await client.delete(f"/ratings/{rating}", headers=user_auth_headers)).status_code == 204
    assert await _chosen(client, user_auth_headers) is None


async def test_a_guest_has_no_history_start(client, restricted_user_auth_headers):
    assert (await client.get("/ratings/history-start", headers=restricted_user_auth_headers)).status_code == 403
    assert (await _choose(client, restricted_user_auth_headers, None)).status_code == 403
