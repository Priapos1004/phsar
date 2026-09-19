"""GET /search/mal — the on-demand MyAnimeList lookup.

The BFS behind this is covered against a stubbed scraper in
tests/services/test_mal_scraper.py. What is left for an endpoint test is the auth
choice, the required query param, and the arguments the handler forwards.

`response_model=list[SearchResultDB]` already makes a shape regression loud — a
leaked `SearchResultDBExtended` is a validation 500, not a plausible 200 — so the
assertion worth having is on the call itself: `seed_mal_id` is the dispatcher's
argument, and this route must never set it.

The service is stubbed at the router's import site, the same seam
tests/services/test_seasonal_sweep.py uses. A real call would reach MAL, and CI's
client id is a placeholder.
"""

import pytest

from app.schemas.search_schema import (
    AttachToExistingAction,
    SearchResultDB,
    SearchResultDBExtended,
)

URL = "/search/mal"


@pytest.fixture
def stub_mal(monkeypatch):
    """Records the kwargs the handler passes, and returns one found anime plus an
    attach action the route must not surface."""
    calls: list[dict] = []

    async def fake(db, query, progress=None, seed_mal_id=None):
        calls.append({"query": query, "progress": progress, "seed_mal_id": seed_mal_id})
        return SearchResultDBExtended(
            search_result_db_list=[
                SearchResultDB(anime_mal_id=84001, unconnected_media_list=[]),
            ],
            unwanted_media=set(),
            attach_actions=[
                AttachToExistingAction(
                    target_mal_id=84002, related_anime_graph={}, all_info={},
                ),
            ],
        )

    monkeypatch.setattr("app.routers.search.handle_search_mal_api_results", fake)
    return calls


async def test_search_mal_requires_authentication(client):
    resp = await client.get(f"{URL}?query=anything")
    assert resp.status_code == 401


async def test_search_mal_rejects_a_restricted_guest(
    client, restricted_user_auth_headers,
):
    """A scrape is a write in effect — it pulls new rows into the catalogue — so
    it gates on require_user_or_admin rather than get_current_user.
    """
    resp = await client.get(
        f"{URL}?query=anything", headers=restricted_user_auth_headers,
    )
    assert resp.status_code == 403


async def test_search_mal_requires_a_query(client, user_auth_headers):
    resp = await client.get(URL, headers=user_auth_headers)
    assert resp.status_code == 422


async def test_search_mal_forwards_query_and_never_seeds(
    client, user_auth_headers, stub_mal,
):
    resp = await client.get(f"{URL}?query=cowboy+bebop", headers=user_auth_headers)
    assert resp.status_code == 200

    assert len(stub_mal) == 1
    assert stub_mal[0]["query"] == "cowboy bebop"
    # seed_mal_id drives the dispatcher's attach path; the public route must not
    # reach it, and no response-model check would catch it if it did.
    assert stub_mal[0]["seed_mal_id"] is None


async def test_search_mal_returns_the_bare_list(client, user_auth_headers, stub_mal):
    resp = await client.get(f"{URL}?query=anything", headers=user_auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert [row["anime_mal_id"] for row in body] == [84001]
    assert "attach_actions" not in resp.text
