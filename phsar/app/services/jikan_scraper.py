import logging
from collections import deque
from typing import Optional

import httpx
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_fixed

from app.exceptions import AnimeNotFoundError

BASE_URL = "https://api.jikan.moe/v4"

logger = logging.getLogger(__name__)


class JikanScraper:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        before_sleep=before_sleep_log(logger, logging.DEBUG)
    )
    async def _get(self, url: str, params: Optional[dict] = None) -> dict:
        logger.debug(f"Fetching URL: {url} with params: {params}")
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def extract_information(self, anime: dict) -> dict:
        genres = (
            [genre["name"] for genre in anime.get("genres", [])]
            + [genre["name"] for genre in anime.get("explicit_genres", [])]
            + [genre["name"] for genre in anime.get("themes", [])]
            + [genre["name"] for genre in anime.get("demographics", [])]
        )
        return {
            "mal_id": anime.get("mal_id"),
            "mal_url": anime.get("url"),
            "title": anime.get("title"),
            "name_eng": anime.get("title_english"),
            "name_jap": anime.get("title_japanese"),
            "other_names": anime.get("title_synonyms", []),
            "media_type": anime.get("type").replace(" ", ""), # For case: "TV Special" and "TVSpecial"
            "genres": genres,
            "studio": [studio["name"] for studio in anime.get("studios", [])],
            "fsk": anime.get("rating"),
            "description": anime.get("synopsis"),
            "original_source": anime.get("source"),
            "cover_image": anime.get("images", {}).get("jpg", {}).get("large_image_url"),
            "score": anime.get("score"),
            "scored_by": anime.get("scored_by"),
            "episodes": anime.get("episodes"),
            "anime_season": f"{anime.get('season', 'Unknown')} {anime.get('year', 'Unknown')}",
            "aired_from": anime.get("aired", {}).get("from"),
            "aired_to": anime.get("aired", {}).get("to"),
            "airing_status": anime.get("status"),
            "duration": anime.get("duration"),
        }

    async def fetch_relations(self, mal_id: int) -> list[dict]:
        data = await self._get(f"{self.base_url}/anime/{mal_id}/relations")
        return data.get("data", [])

    async def search_by_malid(self, mal_id: int) -> dict:
        data = await self._get(f"{self.base_url}/anime/{mal_id}")
        return data.get("data", {})

    def get_all_anime_media(self, media_list: list[dict]) -> list[int]:
        return [media["mal_id"] for media in media_list if media.get("type") == "anime"]

    def get_relation_type(self, is_main_season: bool, relation_type: Optional[str]) -> str:
        return "main" if is_main_season else (relation_type or "other")

    async def search_title(self, title: str, excluded_mal_ids: set[int]) -> tuple[list[dict], dict[int, dict]]:
        search = await self._get(f"{self.base_url}/anime", params={"q": title, "limit": 3})
        results = search.get("data", [])

        if not results:
            raise AnimeNotFoundError(title)

        all_info: dict[int, dict] = {}
        visited_ids: set[int] = excluded_mal_ids
        relations: list[dict] = []

        for anime in results:
            anime_info = self.extract_information(anime)
            logger.info(f"Searching relations with: {anime_info['title']}")
            mal_id = anime_info["mal_id"]
            related_anime_graph: dict[int, dict] = {}
            left_mal_ids = deque([mal_id])
            relation_types = deque([None])

            while left_mal_ids:
                current_mal_id = left_mal_ids.popleft()
                current_relation = relation_types.popleft()

                if current_mal_id in visited_ids:  # skip if visited
                    continue
                
                logger.info(f"Media left in recursive search: {len(set(left_mal_ids) - visited_ids)}")
                # Mark as visited BEFORE doing anything
                visited_ids.add(current_mal_id)

                if mal_id != current_mal_id:
                    anime_info = self.extract_information(await self.search_by_malid(current_mal_id))

                if anime_info.get("media_type"):
                    if anime_info["media_type"].lower() == "music":
                        logger.warning(f"Skipping anime music: {anime_info['title']}")
                        continue

                    all_info[anime_info["mal_id"]] = anime_info

                    all_related_media = await self.fetch_relations(current_mal_id)
                    relation_types_list = [media["relation"] for media in all_related_media]

                    is_main_season = (
                        current_relation is None
                        and anime_info["media_type"].lower() == "tv"
                        and "full_story" not in relation_types_list
                        and "parent_story" not in relation_types_list
                    )

                    related_anime_graph[anime_info["mal_id"]] = {
                        "mal_id": current_mal_id,
                        "title": anime_info["title"],
                        "aired_from": anime_info["aired_from"],
                        "media_type": anime_info["media_type"],
                        "relation_type": self.get_relation_type(is_main_season, current_relation),
                    }

                    for related_media in all_related_media:
                        rel = related_media["relation"].lower()
                        if rel == 'character': # Skip because not related enough
                            continue

                        if rel != "adaptation":
                            mal_ids = self.get_all_anime_media(related_media["entry"])
                            left_mal_ids.extend(mal_ids)
                            if rel in ["summary"]:
                                relation_types.extend([rel] * len(mal_ids))
                            else:
                                relation_types.extend([None] * len(mal_ids))

                else:
                    logger.warning(f"Anime without media_type:\n{anime_info}")

            if related_anime_graph:
                sorted_graph = dict(
                    sorted(
                        related_anime_graph.items(),
                        key=lambda item: (item[1]["aired_from"] is None, item[1]["aired_from"])
                    )
                )
                relations.append(sorted_graph)

        return relations, all_info
