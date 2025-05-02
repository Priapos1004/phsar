import pytest

from app.exceptions import MalIdAlreadyExistsError


@pytest.mark.asyncio
async def test_save_search_results(client):
    fake_anime_mal_id = -54321

    fake_search_results = [
        {
            "anime_mal_id": fake_anime_mal_id,
            "unconnected_media_list": [
                {
                    "mal_id": fake_anime_mal_id,
                    "mal_url": "https://myanimelist.net/anime/54321/Fake_Anime",
                    "title": "Fake Anime Title",
                    "name_eng": "Fake Anime English",
                    "name_jap": "フェイクアニメ",
                    "other_names": ["Fake Alt Title"],
                    "media_type": "TV",
                    "relation_type": "main",
                    "fsk": "PG-13",
                    "description": "A fake anime used for testing.",
                    "original_source": "Manga",
                    "cover_image": "https://cdn.fake/fakeanime.jpg",
                    "score": 8.7,
                    "scored_by": 12345,
                    "episodes": 12,
                    "anime_season": "Spring 2025",
                    "airing_status": "finished",
                    "aired_from": "2025-04-01T00:00:00",
                    "aired_to": "2025-06-17T00:00:00",
                    "duration": "24 min per ep",
                    "duration_seconds": 1440,
                    "genres": ["Action", "Adventure"],
                    "studio": ["Fake Studio"],
                }
            ]
        }
    ]

    # Step 1: Save successfully
    response = await client.post("/save/search-results", json=fake_search_results)
    assert response.status_code == 200

    # Step 2: Try saving the same anime again — should fail
    with pytest.raises(MalIdAlreadyExistsError):
        response = await client.post("/save/search-results", json=fake_search_results)
