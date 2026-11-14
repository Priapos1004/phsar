"""The recommender's settings and the history start they read: docs/features/recommender.md."""


async def test_the_recommender_settings_default_and_round_trip(client, user_auth_headers):
    """The history start detects until a date is chosen, and clearing it detects again; hot
    anime are recommended unless turned off."""
    settings = (await client.get("/users/settings", headers=user_auth_headers)).json()
    assert (settings["history_start"], settings["recommend_hot"]) == (None, True)
    resp = await client.put(
        "/users/settings", json={"history_start": "2026-07-01", "recommend_hot": False}, headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    start = (await client.get("/ratings/history-start", headers=user_auth_headers)).json()
    assert start == {"detected": None, "chosen": "2026-07-01"}
    await client.put("/users/settings", json={"history_start": None}, headers=user_auth_headers)
    settings = (await client.get("/users/settings", headers=user_auth_headers)).json()
    assert (settings["history_start"], settings["recommend_hot"]) == (None, False)


async def test_a_guest_has_no_history_start(client, restricted_user_auth_headers):
    assert (await client.get("/ratings/history-start", headers=restricted_user_auth_headers)).status_code == 403
