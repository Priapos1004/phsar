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
async def test_media_type(client):
    response = await client.get("/search/media", params={
        "query": "Academia 2",
        "media_type": "TV"
    })
    assert response.status_code == 200
    print("Media type:", response.json())


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
async def test_score_and_episodes(client):
    response = await client.get("/search/media", params={
        "query": "Academia 2",
        "score_min": 7.0,
        "score_max": 9.5,
        "episodes_min": 12
    })
    assert response.status_code == 200
    print("Score and episodes:", response.json())
