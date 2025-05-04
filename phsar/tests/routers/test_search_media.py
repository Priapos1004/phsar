import pytest


@pytest.mark.asyncio
async def test_single_relation_type(client, user_auth_headers):
    response = await client.get("/search/media", params={
        "query": "Academia 2",
        "relation_type": "main"
    }, headers=user_auth_headers)
    assert response.status_code == 200
    print("Single relation_type:", response.json())


@pytest.mark.asyncio
async def test_multiple_relation_types(client, user_auth_headers):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("relation_type", "main"),
        ("relation_type", "summary")
    ], headers=user_auth_headers)
    assert response.status_code == 200
    print("Multiple relation_type:", response.json())


@pytest.mark.asyncio
async def test_genre_and_studio(client, user_auth_headers):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("genre_name", "Action"),
        ("genre_name", "School"),
        ("studio_name", "Bones")
    ], headers=user_auth_headers)
    assert response.status_code == 200
    print("Genre and studio:", response.json())


@pytest.mark.asyncio
async def test_all_filters(client, user_auth_headers):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("relation_type", "main"),
        ("media_type", "TV"),
        ("fsk", "PG-13 - Teens 13 or older"),
        ("airing_status", "Finished Airing"),
        ("anime_season", "Spring 2022"),
        ("genre_name", "Action"),
        ("studio_name", "Bones"),
        ("score_min", 7.0),
        ("score_max", 9.5),
        ("scored_by_min", 1000),
        ("episodes_min", 12),
        ("episodes_max", 24),
        ("duration_per_episode_min", 1200),  # 20 minutes
        ("duration_per_episode_max", 1800),  # 30 minutes
        ("total_watch_time_min", 14400),     # 4 hours
        ("total_watch_time_max", 28800),     # 8 hours
    ], headers=user_auth_headers)
    assert response.status_code == 200
    print("All filters:", response.json())


@pytest.mark.asyncio
async def test_duplicated_genre(client, user_auth_headers):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("genre_name", "Action"),
        ("genre_name", "Action")
    ], headers=user_auth_headers)
    assert response.status_code == 200
    print("Duplicated genres:", response.json())


@pytest.mark.asyncio
async def test_title_searchtype(client, user_auth_headers):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("search_type", "title")
    ], headers=user_auth_headers)
    assert response.status_code == 200
    print("Search type title:", response.json())


@pytest.mark.asyncio
async def test_description_searchtype(client, user_auth_headers):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("search_type", "description")
    ], headers=user_auth_headers)
    assert response.status_code == 200
    print("Search type description:", response.json())


@pytest.mark.asyncio
async def test_empty_string_query(client, user_auth_headers):
    response = await client.get("/search/media", params=[
        ("query", "")
    ], headers=user_auth_headers)
    assert response.status_code == 200
    print("Empty string query:", response.json())


@pytest.mark.asyncio
async def test_empty_query(client, user_auth_headers):
    response = await client.get("/search/media", headers=user_auth_headers)
    assert response.status_code == 200
    print("Empty query:", response.json())

@pytest.mark.asyncio
async def test_duration_per_episode(client, user_auth_headers):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("duration_per_episode_min", 1200),  # 20 min
        ("duration_per_episode_max", 1800),  # 30 min
    ], headers=user_auth_headers)
    assert response.status_code == 200
    print("Duration per episode filter:", response.json())


@pytest.mark.asyncio
async def test_total_watch_time(client, user_auth_headers):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("total_watch_time_min", 14400),  # 4 hours
        ("total_watch_time_max", 28800),  # 8 hours
    ], headers=user_auth_headers)
    assert response.status_code == 200
    print("Total watch time filter:", response.json())


@pytest.mark.asyncio
async def test_edge_case_duration_limits(client, user_auth_headers):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("duration_per_episode_min", 0),      # allow 0 min episodes
        ("duration_per_episode_max", 100000), # absurdly high (for edge test)
    ], headers=user_auth_headers)
    assert response.status_code == 200
    print("Edge case duration limits:", response.json())

async def test_basic_access_to_search_media_admin(client, admin_auth_headers):
    response = await client.get("/search/media", headers=admin_auth_headers)
    assert response.status_code == 200, f"Admin: Expected 200 OK, got {response.status_code}"
    print("[Admin] Basic access check passed.")

async def test_basic_access_to_search_media_restricted_user(client, restricted_user_auth_headers):
    response = await client.get("/search/media", headers=restricted_user_auth_headers)
    assert response.status_code == 200, f"RestrictedUser: Expected 200 OK, got {response.status_code}"
    print("[RestrictedUser] Basic access check passed.")

@pytest.mark.asyncio
async def test_without_token(client):
    response = await client.get("/search/media")
    assert response.status_code == 401, "Expected 401 Unauthorized without token"
    print("Query without token:", response.json())
