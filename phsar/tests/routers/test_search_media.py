import pytest


@pytest.mark.asyncio
async def test_single_relation_type(client):
    response = await client.get("/search/media", params={
        "query": "Academia 2",
        "relation_type": "main"
    })
    assert response.status_code == 200
    print("Single relation_type:", response.json())


@pytest.mark.asyncio
async def test_multiple_relation_types(client):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("relation_type", "main"),
        ("relation_type", "summary")
    ])
    assert response.status_code == 200
    print("Multiple relation_type:", response.json())


@pytest.mark.asyncio
async def test_genre_and_studio(client):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("genre_name", "Action"),
        ("genre_name", "School"),
        ("studio_name", "Bones")
    ])
    assert response.status_code == 200
    print("Genre and studio:", response.json())


@pytest.mark.asyncio
async def test_all_filters(client):
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
    ])
    assert response.status_code == 200
    print("All filters:", response.json())


@pytest.mark.asyncio
async def test_duplicated_genre(client):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("genre_name", "Action"),
        ("genre_name", "Action")
    ])
    assert response.status_code == 200
    print("Duplicated genres:", response.json())


@pytest.mark.asyncio
async def test_title_searchtype(client):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("search_type", "title")
    ])
    assert response.status_code == 200
    print("Search type title:", response.json())


@pytest.mark.asyncio
async def test_description_searchtype(client):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("search_type", "description")
    ])
    assert response.status_code == 200
    print("Search type description:", response.json())


@pytest.mark.asyncio
async def test_empty_string_query(client):
    response = await client.get("/search/media", params=[
        ("query", "")
    ])
    assert response.status_code == 200
    print("Empty string query:", response.json())


@pytest.mark.asyncio
async def test_empty_query(client):
    response = await client.get("/search/media")
    assert response.status_code == 200
    print("Empty query:", response.json())


@pytest.mark.asyncio
async def test_duration_per_episode(client):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("duration_per_episode_min", 1200),  # 20 min
        ("duration_per_episode_max", 1800),  # 30 min
    ])
    assert response.status_code == 200
    print("Duration per episode filter:", response.json())


@pytest.mark.asyncio
async def test_total_watch_time(client):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("total_watch_time_min", 14400),  # 4 hours
        ("total_watch_time_max", 28800),  # 8 hours
    ])
    assert response.status_code == 200
    print("Total watch time filter:", response.json())


@pytest.mark.asyncio
async def test_edge_case_duration_limits(client):
    response = await client.get("/search/media", params=[
        ("query", "Academia 2"),
        ("duration_per_episode_min", 0),      # allow 0 min episodes
        ("duration_per_episode_max", 100000), # absurdly high (for edge test)
    ])
    assert response.status_code == 200
    print("Edge case duration limits:", response.json())
