import logging
import re
from collections import deque
from datetime import datetime
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
        self.timeout = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=self.timeout)
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
    
    @staticmethod
    def __clean_str_field(value: str | None) -> str | None:
        # Clean and normalize the string
        if not isinstance(value, str):
            return None

        # For case: "TV Special" and "TVSpecial"
        cleaned = value.replace(" ", "").strip()

        # Map 'Web' to 'ONA' (Handle legacy type)
        if cleaned.lower() == "web":
            return "ONA"

        return cleaned
    
    @staticmethod
    def __get_anime_season(anime: dict) -> tuple[Optional[str], Optional[int]]:
        season = anime.get("season")
        year = anime.get("year")
        if season and year:
            return season.capitalize(), int(year)

        aired_from = anime.get("aired", {}).get("from")
        if not aired_from:
            return None, None

        try:
            date = datetime.fromisoformat(aired_from.replace("Z", "+00:00"))
            year = date.year
            month = date.month

            if 1 <= month <= 3:
                season = "Winter"
            elif 4 <= month <= 6:
                season = "Spring"
            elif 7 <= month <= 9:
                season = "Summer"
            else:  # 10 <= month <= 12
                season = "Fall"

            return season, year
        except Exception:
            return None, None

    @staticmethod
    def _parse_duration_to_seconds(duration: Optional[str]) -> Optional[int]:
        if not duration or "unknown" in duration.lower():
            return None

        # Match patterns like "1 hr. 30 min.", "24 min.", "2 hr.", "43 sec", etc.
        hours_match = re.search(r"(\d+)\s*hr", duration, re.IGNORECASE)
        minutes_match = re.search(r"(\d+)\s*min", duration, re.IGNORECASE)
        seconds_match = re.search(r"(\d+)\s*sec", duration, re.IGNORECASE)

        hours = int(hours_match.group(1)) if hours_match else 0
        minutes = int(minutes_match.group(1)) if minutes_match else 0
        seconds = int(seconds_match.group(1)) if seconds_match else 0

        total_seconds = (hours * 3600) + (minutes * 60) + seconds
        return total_seconds if total_seconds > 0 else None

    def extract_information(self, anime: dict) -> dict:
        genres = (
            [genre["name"] for genre in anime.get("genres", [])]
            + [genre["name"] for genre in anime.get("explicit_genres", [])]
            + [genre["name"] for genre in anime.get("themes", [])]
            + [genre["name"] for genre in anime.get("demographics", [])]
        )
        anime_season_name, anime_season_year = JikanScraper.__get_anime_season(anime)
        scored_by = anime.get("scored_by") or 0
        return {
            "mal_id": anime.get("mal_id"),
            "mal_url": anime.get("url"),
            "title": anime.get("title"),
            "name_eng": anime.get("title_english"),
            "name_jap": anime.get("title_japanese"),
            "other_names": anime.get("title_synonyms", []),
            "media_type": JikanScraper.__clean_str_field(anime.get("type")),
            "genres": genres,
            "studio": [studio["name"] for studio in anime.get("studios", [])],
            "age_rating": anime.get("rating"),
            "description": anime.get("synopsis"),
            "original_source": anime.get("source"),
            "cover_image": anime.get("images", {}).get("jpg", {}).get("large_image_url"),
            "score": anime.get("score"),
            "scored_by": scored_by,
            "episodes": anime.get("episodes"),
            "anime_season_name": anime_season_name,
            "anime_season_year": anime_season_year,
            "aired_from": anime.get("aired", {}).get("from"),
            "aired_to": anime.get("aired", {}).get("to"),
            "airing_status": anime.get("status"),
            "duration": anime.get("duration"),
            "duration_seconds": JikanScraper._parse_duration_to_seconds(anime.get("duration")),
        }

    async def fetch_relations(self, mal_id: int) -> list[dict]:
        data = await self._get(f"{self.base_url}/anime/{mal_id}/relations")
        return data.get("data", [])

    async def search_by_malid(self, mal_id: int) -> dict:
        data = await self._get(f"{self.base_url}/anime/{mal_id}")
        return data.get("data", {})

    def get_all_anime_media(self, media_list: list[dict]) -> list[int]:
        return [media["mal_id"] for media in media_list if media.get("type") == "anime"]

    def get_relation_type(self, is_main_story: bool, relation_type: Optional[str]) -> str:
        return "main" if is_main_story else (relation_type or "other")

    async def search_title(self, title: str, excluded_mal_ids: set[int], initial_search_limit: int = 3) -> tuple[list[dict], dict[int, dict], set[tuple[int, str, str]]]:
        search = await self._get(f"{self.base_url}/anime", params={"q": title, "limit": initial_search_limit})
        results = search.get("data", [])

        if not results:
            raise AnimeNotFoundError(title)

        all_info: dict[int, dict] = {}
        visited_ids: set[int] = excluded_mal_ids
        relations: list[dict] = []
        unwanted_media: set[tuple[int, str, str]] = set()

        for anime in results:
            anime_info = self.extract_information(anime)
            logger.info(f"Searching relations with: {anime_info['title']}")
            mal_id = anime_info["mal_id"]
            related_anime_graph: dict[int, dict] = {}
            left_mal_ids = deque([mal_id])
            relation_types = deque([None])
            is_first_relation = True # Skip first anime and come back later via relations (if it has relations)
            found_main_story = False # Search side-stories till main story is found. Then only search relations for main stories

            while left_mal_ids:
                current_mal_id = left_mal_ids.popleft()
                current_relation = relation_types.popleft()

                if current_mal_id in visited_ids:  # skip if visited
                    continue
                
                logger.info(f"Media left in recursive search: {len(set(left_mal_ids) - visited_ids)}")

                # Mark as visited BEFORE doing anything
                visited_ids.add(current_mal_id)

                if current_mal_id != mal_id:
                    anime_info = self.extract_information(await self.search_by_malid(current_mal_id))
                elif not is_first_relation:
                    # Seeing first anime organically again
                    anime_info = self.extract_information(anime)

                if anime_info.get("media_type"):
                    if anime_info["media_type"].lower() in ["music", "pv", "cm"]:
                        logger.warning(f"Skipping anime {anime_info['media_type']}: {anime_info['title']}")
                        unwanted_media.add((current_mal_id, anime_info["title"], anime_info["media_type"]))
                        continue
                    elif any("hentai" == genre_name.lower() for genre_name in anime_info["genres"]):
                        logger.warning(f"Skipping anime hentai: {anime_info['title']}")
                        unwanted_media.add((current_mal_id, anime_info["title"], "Hentai"))
                        continue
                    
                    all_info[current_mal_id] = anime_info

                    all_related_media = await self.fetch_relations(current_mal_id)
                    relation_types_list = [media["relation"] for media in all_related_media]

                    is_main_story = (
                        current_relation is None
                        and anime_info["media_type"].lower() in ["tv", "movie"]
                        and "full_story" not in relation_types_list
                        and "parent_story" not in relation_types_list
                    )

                    related_anime_graph[current_mal_id] = {
                        "mal_id": current_mal_id,
                        "title": anime_info["title"],
                        "aired_from": anime_info["aired_from"],
                        "media_type": anime_info["media_type"],
                        "relation_type": self.get_relation_type(is_main_story, current_relation),
                    }

                    if is_main_story or is_first_relation or not found_main_story:
                        for related_media in all_related_media:
                            rel = related_media["relation"].lower()
                            if rel == 'character': # Skip because not related enough
                                continue

                            if rel != "adaptation": # Skip adaptation which are mangas, light novels, etc.
                                mal_ids = self.get_all_anime_media(related_media["entry"])
                                left_mal_ids.extend(mal_ids)
                                if rel in ["summary", "crossover"]:
                                    relation_types.extend([rel] * len(mal_ids))
                                elif rel in ["side_story", "alternative_version", "compilation"]:
                                    relation_types.extend(["other"] * len(mal_ids))
                                else:
                                    relation_types.extend([None] * len(mal_ids))

                        if len(left_mal_ids) > 0 and is_first_relation and is_main_story:
                            # Remove current_mal_id from visited_ids, all_info, and related_anime_graph -> find it organically again
                            visited_ids.discard(current_mal_id)
                            all_info.pop(current_mal_id)
                            related_anime_graph.pop(current_mal_id)
                        elif is_main_story and not found_main_story:
                            # Found main story -> only search relations of main stories
                            found_main_story = True
                        elif len(left_mal_ids) == 0 and is_first_relation and not is_main_story:
                            # Orphaned side-story media -> main story
                            logger.warning(f"Orphaned side-story detected: {anime_info['title']} ({current_mal_id})")
                            related_anime_graph[current_mal_id]["relation_type"] = "main"

                        if is_first_relation:
                            is_first_relation = False
                else:
                    logger.warning(f"Anime without media_type:\n{anime_info}")
                    unwanted_media.add((current_mal_id, anime_info["title"], "Unknown"))
            
                # Case that the original anime was not found organically again
                if (len(left_mal_ids) == 0) and (mal_id not in visited_ids):
                    logger.info(f"Re-enqueuing original anime {anime_info['title']} ({mal_id}) because it was not found organically.")
                    left_mal_ids.append(mal_id)
                    relation_types.append(None)

            # Case that no main story was found but more than one media
            # will be catched in search_service.py with MainMediaNotFoundError

            if related_anime_graph:
                sorted_graph = dict(
                    sorted(
                        related_anime_graph.items(),
                        key=lambda item: (item[1]["aired_from"] is None, item[1]["aired_from"])
                    )
                )
                relations.append(sorted_graph)

        return relations, all_info, unwanted_media
