"""POST /seed/media — the internal catalogue seeding entry point.

Only the authorization boundary is pinned here. The work behind it is
`handle_search_mal_api_results` + `save_search_results`, both covered against a
stubbed scraper in tests/services/test_mal_scraper.py and tests/routers/test_save.py;
re-driving them through this endpoint would re-test them over real MAL queries
without pinning anything new. What only an HTTP test reaches is that
`require_admin` is bound on this handler at all: the router carries no
`dependencies=`, so the gate is per-route. That matters more here than the 403
suggests — the handler walks POPULAR_ANIME_QUERIES firing a live MAL search per
entry, so an ungated call is an unauthenticated scrape trigger.

These three cover the one route that exists. They cannot catch a *new* unguarded
handler added beside it, which is the hazard `.claude/rules/backend.md` names for
this module and for admin_jobs; a route-table walk over `create_app().routes`
would, and belongs with both.
"""

URL = "/seed/media"


async def test_seed_requires_authentication(client):
    resp = await client.post(URL)
    assert resp.status_code == 401


# Two tests rather than a parametrize over the fixture names: the auth-header
# fixtures are async, and `request.getfixturevalue` cannot resolve those from
# inside a running loop.
async def test_seed_rejects_a_plain_user(client, user_auth_headers):
    resp = await client.post(URL, headers=user_auth_headers)
    assert resp.status_code == 403


async def test_seed_rejects_a_restricted_guest(client, restricted_user_auth_headers):
    resp = await client.post(URL, headers=restricted_user_auth_headers)
    assert resp.status_code == 403
