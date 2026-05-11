import asyncio
import logging
import re
from collections import deque
from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING, Optional

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    wait_exponential,
)

from app.exceptions import AnimeNotFoundError, TransientUpstreamError


def _is_transient_mal_error(exc: BaseException) -> bool:
    """5xx, 429, timeouts, and network errors are transient and worth
    retrying. Other 4xx (most importantly 404) is deterministic — same
    request will fail the same way, so burning exponential backoff
    just delays the inevitable failure.

    429 is special-cased BECAUSE the rate limiter (1 req/s, matching
    MAL's 60 req/min sustained ceiling) leaves zero headroom: a brief
    per-minute window overrun can produce 429 even though our average
    request rate is correct. Limited retry with backoff (capped at
    3 attempts by _stop_strategy below) bridges the per-minute window
    without giving up on a single transient rejection. The tight cap
    is deliberate — if we're consistently 429'd, retrying harder
    masks sustained abuse instead of fixing it; the right response
    then is to slow the source rate, not retry more."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))


def _stop_strategy(retry_state) -> bool:
    """Asymmetric retry budget: 3 total attempts for 429, 5 for
    everything else (5xx/timeouts/network). The lower 429 cap keeps a
    failing job from burning 31s+ of backoff when MAL is sustained-
    limiting us — 2 retries are enough to bridge a misaligned
    per-minute window; beyond that, retrying just delays the
    inevitable failure (and the job stays retryable=True so user-
    facing flows can re-submit from the bell)."""
    if retry_state.attempt_number >= 5:
        return True
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return retry_state.attempt_number >= 3
    return False

if TYPE_CHECKING:
    from app.services.progress_reporter import ProgressReporter

BASE_URL = "https://api.jikan.moe/v4"

# Sentinel media.airing_status values MAL returns. Module-level so callers
# (sweep tier query, dispatcher diff, the not-yet-aired blacklist guard)
# don't drift onto separate string copies.
AIRING_STATUS_CURRENTLY_AIRING = "Currently Airing"
AIRING_STATUS_NOT_YET_AIRED = "Not yet aired"

logger = logging.getLogger(__name__)


def parse_mal_datetime(value: str | None) -> Optional[datetime]:
    # MAL emits "+00:00" most of the time but historical payloads sometimes
    # carry "Z". `fromisoformat` accepts the former natively.
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class JikanScraper:
    # Jikan documents 3 req/s burst AND 60 req/min sustained. The
    # per-minute ceiling is the binding constraint for the seasonal
    # sweep's `/seasons/now` pagination and the update sweep's
    # bulk-refresh path: both fire continuous requests with no idle
    # window to amortize the average. 350ms (~2.85/s) and 500ms (~2/s)
    # both observed 429s in practice — neither stays under 60/min for
    # sustained traffic. 1000ms (1 req/s) is the documented sustained
    # ceiling. Jikan's docs also note "It's still possible to get rate
    # limited from MyAnimeList.net instead" — MAL upstream can throttle
    # us regardless of Jikan headroom, but staying under the documented
    # limit minimizes that risk. tenacity intentionally skips 4xx retry:
    # retrying 429 wouldn't reduce IP-ban risk, slowing the source is
    # what helps. Class-level so user_scrape and update_sweep share the
    # gate if they ever overlap.
    _MIN_REQUEST_INTERVAL_S: float = 1.0
    _rate_lock: asyncio.Lock = asyncio.Lock()
    _last_request_at: float = 0.0

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.client: Optional[httpx.AsyncClient] = None
        self.timeout = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.client.aclose()

    @classmethod
    async def _wait_for_rate_limit(cls) -> None:
        """Serialized lock + sleep keeps consecutive request *starts* at
        least _MIN_REQUEST_INTERVAL_S apart. Tenacity retries reinvoke
        _get and hit this gate too — fine, since the backoff already
        dominates the wait."""
        async with cls._rate_lock:
            now = monotonic()
            elapsed = now - cls._last_request_at
            if elapsed < cls._MIN_REQUEST_INTERVAL_S:
                await asyncio.sleep(cls._MIN_REQUEST_INTERVAL_S - elapsed)
                now = monotonic()
            cls._last_request_at = now

    @retry(
        # Exponential backoff caps at 30s — better tail behavior on a transient
        # MAL outage than fixed-1s, especially during overnight unattended runs.
        # Asymmetric budget: 429 caps at 3 attempts (2 retries — enough to
        # bridge a misaligned per-minute window), other transients at 5.
        # See _stop_strategy above.
        stop=_stop_strategy,
        wait=wait_exponential(multiplier=2, min=1, max=30),
        # Skip 4xx (404 from a misspelled query is deterministic; retrying
        # wastes 31s of backoff before failing the same way).
        retry=retry_if_exception(_is_transient_mal_error),
        # Surface the underlying HTTPStatusError / TimeoutException to the
        # caller instead of wrapping it in tenacity's RetryError. The bell's
        # `result_summary["error"]` becomes the human-readable upstream
        # message ("Server error '504 Gateway Time-out' for url '...'")
        # instead of `RetryError[<Future at 0x... state=finished raised ...>]`.
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.DEBUG)
    )
    async def _get(self, url: str, params: Optional[dict] = None) -> dict:
        logger.debug(f"Fetching URL: {url} with params: {params}")
        await self._wait_for_rate_limit()
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
            date = parse_mal_datetime(aired_from)
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

    async def refresh_anime(self, mal_id: int) -> dict:
        # /full bundles relations into the same response, so 7c's probe
        # can read them without a second hit. 7b ignores the relations
        # block and just diffs the canonical fields.
        data = await self._get(f"{self.base_url}/anime/{mal_id}/full")
        return data.get("data", {})

    async def fetch_current_season(self) -> list[dict]:
        """Paginate `/seasons/now` and return the raw anime entries.

        Each page response shape: `{"data": [...], "pagination": {
        "has_next_page": bool, ...}}`. The dispatcher only needs
        `mal_id` + `title` per entry — no `extract_information` here,
        the seasonal sweep just hands the title down to a child
        `user_scrape` job that fetches the full record itself.
        """
        results: list[dict] = []
        page = 1
        while True:
            payload = await self._get(
                f"{self.base_url}/seasons/now", params={"page": page},
            )
            entries = payload.get("data", []) or []
            results.extend(entries)
            if not payload.get("pagination", {}).get("has_next_page"):
                break
            page += 1
        return results

    def get_all_anime_media(self, media_list: list[dict]) -> list[int]:
        return [media["mal_id"] for media in media_list if media.get("type") == "anime"]

    def get_relation_type(self, is_main_story: bool, relation_type: Optional[str]) -> str:
        return "main" if is_main_story else (relation_type or "side_story")

    async def search_title(
        self,
        title: str | None,
        excluded_mal_ids: set[int],
        initial_search_limit: int = 3,
        progress: "ProgressReporter | None" = None,
        seed_mal_id: int | None = None,
        seed_payload: dict | None = None,
    ) -> tuple[
        list[tuple[dict, set[int]]],
        dict[int, dict],
        set[tuple[int, str, str]],
    ]:
        if seed_mal_id is not None:
            # Probe path: skip the q= search; use the seed's own /full
            # payload (already in the dispatcher's hand) as the single
            # candidate. Subtract the seed from excluded_ids so the BFS
            # actually processes it instead of short-circuiting on
            # "already in catalog".
            seed_data = seed_payload or await self.search_by_malid(seed_mal_id)
            if not seed_data:
                # MAL returned 200 OK but the `data` field was empty/null
                # — a real 404 would have raised HTTPStatusError inside
                # `_get`. This is a transient MAL data hiccup (observed
                # in practice: legitimate mal_ids briefly return empty
                # payloads). Use TransientUpstreamError so the worker
                # marks the job retryable=True; otherwise a single
                # cosmic-ray MAL response permanently locks the mal_id
                # out via the 72h dedup window for user jobs and gets
                # stamped as a Permanent failure that no one can retry.
                raise TransientUpstreamError(f"mal_id={seed_mal_id}")
            results = [seed_data]
            excluded_ids: frozenset[int] = frozenset(excluded_mal_ids - {seed_mal_id})
        else:
            if title is None:
                raise ValueError("search_title requires either title or seed_mal_id")
            search = await self._get(f"{self.base_url}/anime", params={"q": title, "limit": initial_search_limit})
            results = search.get("data", [])
            if not results:
                raise AnimeNotFoundError(title)
            # excluded_ids = pre-existing in catalog (frozen for the run);
            # visited_ids = traversed in *this* run. Splitting them so we can
            # detect "BFS hit a media that already lives under a different anime
            # in the catalog" — that's the relation_link merge-candidate signal.
            excluded_ids: frozenset[int] = frozenset(excluded_mal_ids)

        all_info: dict[int, dict] = {}
        visited_ids: set[int] = set()
        relations: list[tuple[dict, set[int]]] = []
        unwanted_media: set[tuple[int, str, str]] = set()

        for anime in results:
            anime_info = self.extract_information(anime)
            logger.info(f"Searching relations with: {anime_info['title']}")
            mal_id = anime_info["mal_id"]
            related_anime_graph: dict[int, dict] = {}
            cross_link_mal_ids: set[int] = set()
            left_mal_ids = deque([mal_id])
            relation_types = deque([None])
            is_first_relation = True # Skip first anime and come back later via relations (if it has relations)
            found_main_story = False # Search side-stories till main story is found. Then only search relations for main stories

            while left_mal_ids:
                current_mal_id = left_mal_ids.popleft()
                current_relation = relation_types.popleft()

                if current_mal_id in visited_ids:  # already processed this run
                    continue

                if current_mal_id in excluded_ids:
                    # Already in our catalog under some anime parent. If we
                    # reached it via a non-crossover relation from the
                    # current graph (and it isn't the search-entry node
                    # itself), it's a relation_link signal that the new
                    # anime overlaps an existing one. The owning anime is
                    # resolved later in save_service.
                    if current_mal_id != mal_id and current_relation != "crossover":
                        cross_link_mal_ids.add(current_mal_id)
                    visited_ids.add(current_mal_id)
                    continue

                logger.info(f"Media left in recursive search: {len(set(left_mal_ids) - visited_ids - excluded_ids)}")

                # Mark as visited BEFORE doing anything
                visited_ids.add(current_mal_id)

                if progress is not None:
                    discovered = len(visited_ids)
                    # Estimate total as discovered-so-far plus the still-queued
                    # frontier; the frontier has duplicates so this overshoots
                    # slightly but always converges to 100% as the queue drains.
                    await progress.update(
                        items_done=discovered,
                        items_total=discovered + len(left_mal_ids),
                    )

                if current_mal_id != mal_id:
                    anime_info = self.extract_information(await self.search_by_malid(current_mal_id))
                elif not is_first_relation:
                    # Seeing first anime organically again
                    anime_info = self.extract_information(anime)

                # Skip null-title entries without blacklisting — same
                # sentinel pattern as `Not yet aired` below. MAL routinely
                # leaves `title=null` on entries it's still populating
                # (romanization-pending Chinese/Korean shows, brand-new PV
                # stubs); the field reliably fills in within hours. A
                # permanent MediaUnwanted entry with a placeholder title
                # would (a) block re-discovery once MAL titles the row
                # properly and (b) pollute the admin-only table with
                # `<mal_id:NNNN>` strings instead of the real name we'd
                # get on the next sweep. The BFS stops here, so this
                # entry's relations are temporarily out of reach — same
                # cost as Not-yet-aired and acceptable for a transient
                # state.
                if anime_info.get("title") is None:
                    logger.info(
                        "Skipping null-title anime mal_id=%s; MAL hasn't "
                        "populated title yet, next sweep will retry",
                        current_mal_id,
                    )
                    continue

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

                    # Crossover nodes mark a franchise boundary — record the
                    # anime in the graph but don't BFS further. Without this,
                    # a single Fate × Tsukihime crossover collapses both
                    # franchises into one anime row.
                    if current_relation == "crossover":
                        all_related_media = []
                    elif current_mal_id == mal_id and seed_payload is not None:
                        # The /full payload the dispatcher just fetched
                        # already bundles relations; reuse them instead of
                        # paying for a second MAL hit per seed.
                        all_related_media = seed_payload.get("relations") or []
                    else:
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

                            # `alternative setting` is excluded alongside
                            # `adaptation` because it labels separate franchises
                            # that share themes only (e.g., Zhe Tian ↔ Wanmei
                            # Shijie, Madoka ↔ Magia Record). Walking it would
                            # conflate distinct donghua / shows into one Anime
                            # row and produce false-positive merge candidates.
                            # `crossover` stays in the queue (graph boundary,
                            # not full skip) because crossover anime really
                            # ARE part of both franchises.
                            #
                            # NOTE: MAL emits multi-word relations with a space
                            # ("Side Story", "Alternative Setting"); the
                            # `.lower()` above keeps the space, so the literal
                            # to match here is "alternative setting" with a
                            # space, NOT the underscore form some other checks
                            # below use. (Those underscore checks are a known
                            # latent issue worth a separate fix; in scope here
                            # is just the new alt-setting boundary cut.)
                            if rel not in ("adaptation", "alternative setting"):
                                mal_ids = self.get_all_anime_media(related_media["entry"])
                                left_mal_ids.extend(mal_ids)
                                if rel in ["summary", "crossover"]:
                                    relation_types.extend([rel] * len(mal_ids))
                                elif rel in ["side_story", "alternative_version", "compilation"]:
                                    relation_types.extend(["side_story"] * len(mal_ids))
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
                elif anime_info.get("airing_status") == AIRING_STATUS_NOT_YET_AIRED:
                    # Skip without blacklisting — MAL fills the type once the
                    # show airs. A permanent unwanted entry would silently
                    # block the catalog from ever picking it up.
                    logger.info(
                        "Skipping unscheduled anime without media_type: %s (mal_id=%s)",
                        anime_info.get("title"), current_mal_id,
                    )
                else:
                    logger.warning(f"Anime without media_type:\n{anime_info}")
                    unwanted_media.add((current_mal_id, anime_info["title"], "Unknown"))
            
                # Case that the original anime was not found organically again
                if (len(left_mal_ids) == 0) and (mal_id not in visited_ids):
                    logger.info(f"Re-enqueuing original anime {anime_info['title']} ({mal_id}) because it was not found organically.")
                    left_mal_ids.append(mal_id)
                    relation_types.append(None)

            # Post-loop safety net for the seed. The drop branch above
            # (is_main_story + has-relations + is_first_relation) removes
            # the seed from `visited_ids`, `all_info`, and the graph,
            # expecting BFS to organically rediscover it via a relation
            # from one of its sub-graph nodes pointing back. That works
            # for franchises like Demon Slayer (Sequel → original); it
            # fails for Rilakkuma-style cases where the seed's only
            # outgoing relation is `Other` and no node points back —
            # the BFS terminates without ever re-encountering the seed,
            # and the inline bottom-of-loop re-enqueue check is bypassed
            # whenever the last popped node hit a `continue` path
            # (visited / excluded / null-title / filtered). Without this
            # net, the graph ends up missing the seed entirely → no
            # `main` relation → MainMediaNotFoundError → whole scrape
            # fails. The seed was is_main_story=True at drop time (that's
            # the only branch that drops), so re-adding with
            # relation_type="main" matches the intended classification.
            if mal_id not in visited_ids:
                seed_info = self.extract_information(anime)
                if seed_info.get("title") and seed_info.get("media_type"):
                    all_info[mal_id] = seed_info
                    related_anime_graph[mal_id] = {
                        "mal_id": mal_id,
                        "title": seed_info["title"],
                        "aired_from": seed_info["aired_from"],
                        "media_type": seed_info["media_type"],
                        "relation_type": "main",
                    }
                    visited_ids.add(mal_id)
                    logger.info(
                        "BFS recovered dropped seed mal_id=%s as main (post-loop net)",
                        mal_id,
                    )

            # Case that no main story was found but more than one media
            # will be catched in search_service.py with MainMediaNotFoundError

            if related_anime_graph:
                sorted_graph = dict(
                    sorted(
                        related_anime_graph.items(),
                        key=lambda item: (item[1]["aired_from"] is None, item[1]["aired_from"])
                    )
                )
                relations.append((sorted_graph, cross_link_mal_ids))

        return relations, all_info, unwanted_media
