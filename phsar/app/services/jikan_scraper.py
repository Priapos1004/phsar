import asyncio
import enum
import logging
import re
from collections import deque
from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    wait_exponential,
)

from app.exceptions import AnimeNotFoundError, TransientUpstreamError
from app.services.relation_classifier import anchor_tier


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
# (sweep tier query, dispatcher diff, the not-yet-aired blacklist guard,
# the anime-card status derivation, and the anime-view search filter)
# don't drift onto separate string copies.
AIRING_STATUS_CURRENTLY_AIRING = "Currently Airing"
AIRING_STATUS_FINISHED_AIRING = "Finished Airing"
AIRING_STATUS_NOT_YET_AIRED = "Not yet aired"

logger = logging.getLogger(__name__)


def parse_mal_datetime(value: str | None) -> datetime | None:
    # MAL emits "+00:00" most of the time but historical payloads sometimes
    # carry "Z". `fromisoformat` accepts the former natively.
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_relation(rel: str) -> str:
    """MAL emits multi-word relations title-cased with a space
    ("Side Story", "Parent story", "Alternative Setting"). Normalize
    once on entry so every downstream comparison uses the same
    underscore form."""
    return rel.lower().replace(" ", "_")


# Relation labels excluded from edge capture: `character` is not a
# franchise membership signal; `adaptation` and `alternative_setting`
# label cross-franchise links (manga adaptation, themed-shared but
# distinct shows) — walking them collapses distinct shows into one
# anime row.
_EXCLUDED_EDGE_RELS = frozenset({"character", "adaptation", "alternative_setting"})


# Relations that propagate "could be main chain of this graph" identity.
# Everything else MAL emits (side_story, parent_story, summary, full_story,
# other, spin-off) is identity-breaking: it connects related-but-distinct
# members. Without bounding the BFS at identity-breaking edges, a chain of
# weak edges (typically `other → other`) bridges two franchises — the
# Overlord → Eminence in Shadow regression caused by MAL labeling the
# `Ple Ple Pleiades x Kagejitsu!` collab special with relation `Other`
# instead of `Crossover`. See tests/services/test_jikan_scraper.py::
# test_search_title_overlord_pleiades_x_kagejitsu_does_not_bridge_to_eminence.
_IDENTITY_PRESERVING_RELS = frozenset({"sequel", "prequel", "alternative_version"})


# Relations MAL uses to point a derivative work at its canonical ancestor
# (Movie → full_story → TV; side-story → parent_story → TV; later-in-chain
# → prequel → earlier). Anchor discovery walks ONLY these to find the
# canonical Main from any starting point in the franchise. Critically,
# `other` is intentionally absent — that's where cross-franchise bridges
# live (Ple Ple Pleiades x Kagejitsu, Eva ↔ Ultraman). `alternative_version`
# is also absent: it's lateral within a franchise (Eva TV ↔ Rebuilds), and
# the main BFS already propagates WALK across it as an identity-preserving
# relation, so we don't need to fetch via the anchor pass.
_STRUCTURAL_UPWARD_RELS = frozenset({"prequel", "parent_story", "full_story"})

# Defensive cap on the upward walk in case MAL data has pathological
# structure (cycles, absurdly long chains). Typical franchises are 2-5
# hops; 10 is comfortably above worst-case observed.
_ANCHOR_DISCOVERY_MAX_HOPS = 10


class _ExpandStatus(enum.IntEnum):
    """Ordered ascending so `max()` resolves multi-path arrivals to the
    most-permissive status — a node first queued TERMINAL via `side_story`
    upgrades to WALK if a sequel edge from the same parent points at it."""

    TERMINAL = 0  # Fetch info + relations (for sidecar edges) but don't queue targets.
    WALK = 1      # Full BFS — propagate WALK only along identity-preserving edges.


def _next_expand_status(parent: _ExpandStatus, rel: str) -> _ExpandStatus:
    """State transition: from a WALK parent, only identity-preserving edges
    (sequel/prequel/alternative_version) keep the target WALK. Everything
    else demotes to TERMINAL (in graph with its own outgoing edges
    captured, but BFS doesn't recurse from there).
    """
    if parent is _ExpandStatus.WALK and rel in _IDENTITY_PRESERVING_RELS:
        return _ExpandStatus.WALK
    return _ExpandStatus.TERMINAL


def parse_relation_edges(raw: list[dict]) -> list[tuple[int, str]]:
    """Project a MAL `/anime/{id}/relations` response into
    `[(target_mal_id, normalized_rel), ...]`. Applies the cross-
    franchise edge filter so callers don't have to re-implement it."""
    out: list[tuple[int, str]] = []
    for rel_block in raw:
        rel = normalize_relation(rel_block.get("relation", ""))
        if rel in _EXCLUDED_EDGE_RELS:
            continue
        for entry in rel_block.get("entry", []) or []:
            if entry.get("type") == "anime":
                out.append((entry["mal_id"], rel))
    return out


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
        self.client: httpx.AsyncClient | None = None
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
    async def _get(self, url: str, params: dict | None = None) -> dict:
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
    def __get_anime_season(anime: dict) -> tuple[str | None, int | None]:
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

    # MAL synopses commonly end with one or more credit tags
    # ("[Written by MAL Rewrite]", "[Source: AniDB]", "[Source: Anime News
    # Network]", sometimes stacked). They aren't part of the plot, hurt
    # description-embedding quality, and read as noise to humans. Stripped
    # at scrape AND refresh time so existing rows clean up on nightly sweep
    # once the sweep diffs description (see metadata bucket in
    # scrape_dispatcher).
    _SYNOPSIS_CREDIT_TAG_RE = re.compile(
        r"\s*\[(?:Source|Written by)[^\]]*\]\s*$",
        re.IGNORECASE,
    )

    @staticmethod
    def _clean_synopsis(synopsis: str | None) -> str | None:
        if not synopsis:
            return synopsis
        cleaned = synopsis
        # Loop to peel stacked tags ("...\n\n[Source: A]\n\n[Written by MAL Rewrite]").
        while True:
            stripped = JikanScraper._SYNOPSIS_CREDIT_TAG_RE.sub("", cleaned)
            if stripped == cleaned:
                break
            cleaned = stripped
        cleaned = cleaned.strip()
        return cleaned or None

    @staticmethod
    def _parse_duration_to_seconds(duration: str | None) -> int | None:
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
            "description": JikanScraper._clean_synopsis(anime.get("synopsis")),
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

    async def _discover_anchors_upward(
        self,
        start_mal_id: int,
        excluded_ids: frozenset[int],
        relation_cache: dict[int, list[dict]],
    ) -> set[int]:
        """Walk structural-upward (`prequel` / `parent_story` / `full_story`)
        from `start_mal_id` and return the upmost non-catalog mal_ids reached.

        Used as a pre-BFS pass in `search_title` so a fuzzy MAL search that
        lands on a side-story / summary movie still discovers the franchise's
        canonical Main (e.g. Overlord Movie 1 → full_story → Overlord S1).
        Without this, strict-BFS produces entry-point-dependent graphs when
        no search root is on the canonical sequel chain.

        `other` is intentionally NOT walked — cross-franchise bridges live
        there. `alternative_version` is also out: it's lateral within a
        franchise, and the main BFS propagates WALK across it natively.

        Stops at:
          - `excluded_ids` (catalog members): main BFS surfaces as cross_link.
          - terminal nodes (no upward edges): added to `discovered`.
          - `_ANCHOR_DISCOVERY_MAX_HOPS`: frontier becomes fallback anchors
            so pathological data never produces zero output.

        Caches fetched `/relations` payloads into `relation_cache` so the
        main BFS doesn't re-fetch.
        """
        discovered: set[int] = set()
        visited: set[int] = {start_mal_id}
        frontier: list[int] = [start_mal_id]
        hops = 0

        while frontier and hops < _ANCHOR_DISCOVERY_MAX_HOPS:
            next_frontier: list[int] = []
            for mal_id in frontier:
                if mal_id != start_mal_id and mal_id in excluded_ids:
                    continue

                if mal_id not in relation_cache:
                    relation_cache[mal_id] = await self.fetch_relations(mal_id)

                all_upward = [
                    target for target, rel in parse_relation_edges(
                        relation_cache[mal_id],
                    )
                    if rel in _STRUCTURAL_UPWARD_RELS
                ]

                # A node is an anchor candidate only if it has NO upward
                # edges at all — i.e. it's a true chain start (S1, Eva TV,
                # etc.). Intermediate nodes whose upward targets are
                # already-visited or excluded are NOT anchors — adding them
                # would prepend a mid-chain node ahead of the true root,
                # which then walks to the root via an identity-breaking
                # edge (e.g. Movie 1 → full_story → S1) and demotes the
                # root to TERMINAL.
                if not all_upward:
                    if mal_id != start_mal_id:
                        discovered.add(mal_id)
                    continue

                for target in all_upward:
                    if target in visited or target in excluded_ids:
                        continue
                    visited.add(target)
                    next_frontier.append(target)

            frontier = next_frontier
            hops += 1

        # Pathological-chain fallback: if we hit the hop cap with non-empty
        # frontier, treat those as discovered anchors. Better to over-fetch
        # than to silently fail to find an anchor.
        discovered.update(frontier)
        return discovered

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

    async def search_title(
        self,
        title: str | None,
        excluded_mal_ids: set[int],
        initial_search_limit: int = 3,
        progress: "ProgressReporter | None" = None,
        seed_mal_id: int | None = None,
        seed_payload: dict | None = None,
    ) -> tuple[
        list[tuple[dict, list[tuple[int, int, str]], set[int]]],
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
                # out via the dedup window for user jobs and gets
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

        # Anchor discovery pre-pass: from each search root, walk structural-
        # upward relations to find the canonical chain start. Prepend
        # discovered anchors to `results` so they're processed FIRST in the
        # main BFS — their WALK propagation populates `visited_ids` with the
        # full franchise before subsequent (often side-story-shaped)
        # original-seed iterations run. Cache /relations payloads here so
        # the main BFS doesn't re-fetch.
        relation_cache: dict[int, list[dict]] = {}
        if seed_payload is not None and seed_mal_id is not None:
            relation_cache[seed_mal_id] = seed_payload.get("relations") or []

        existing_mal_ids = {result["mal_id"] for result in results}
        anchor_candidates: list[int] = []
        for result in results:
            discovered_anchors = await self._discover_anchors_upward(
                result["mal_id"], excluded_ids, relation_cache,
            )
            for mal_id in discovered_anchors:
                if mal_id not in existing_mal_ids and mal_id not in anchor_candidates:
                    anchor_candidates.append(mal_id)

        if anchor_candidates:
            anchor_results: list[dict] = []
            for mal_id in anchor_candidates:
                payload = await self.search_by_malid(mal_id)
                if payload:
                    anchor_results.append(payload)
            results = anchor_results + results

        # Process the canonical-est node first. `visited_ids` is shared
        # across iters, so if MAL's fuzzy search returns a non-canonical
        # entry first (Eva case: top hit `Evangelion: Chao Xianshi` ONA
        # has `other → Eva TV`, which would demote Eva TV to TERMINAL and
        # lock it out of iter 3 where Eva TV is the actual root), sorting
        # ensures the TV-shaped chain root walks the franchise BEFORE any
        # side-story-shaped result iter does.
        def _search_result_tier_sort(payload: dict) -> tuple:
            aired_from = (payload.get("aired") or {}).get("from") or ""
            return (anchor_tier(payload.get("type")), aired_from)

        results.sort(key=_search_result_tier_sort)

        all_info: dict[int, dict] = {}
        visited_ids: set[int] = set()
        relations: list[tuple[dict, list[tuple[int, int, str]], set[int]]] = []
        unwanted_media: set[tuple[int, str, str]] = set()

        for anime in results:
            anime_info = self.extract_information(anime)
            logger.info(f"Searching relations with: {anime_info['title']}")
            mal_id = anime_info["mal_id"]
            related_anime_graph: dict[int, dict] = {}
            edges: list[tuple[int, int, str]] = []
            cross_link_mal_ids: set[int] = set()
            left_mal_ids = deque([mal_id])
            expand_by_mal_id: dict[int, _ExpandStatus] = {mal_id: _ExpandStatus.WALK}
            # Tracks mal_ids queued via a `crossover` edge so they're
            # treated as franchise boundaries (no further walking, no
            # relation_link signal).
            crossover_arrivals: set[int] = set()

            while left_mal_ids:
                current_mal_id = left_mal_ids.popleft()

                if current_mal_id in visited_ids:
                    continue

                if current_mal_id in excluded_ids:
                    # Already in catalog. Non-crossover crossings from the
                    # current graph become relation_link merge-candidate
                    # signals; the owning anime is resolved later in
                    # save_service.
                    if current_mal_id != mal_id and current_mal_id not in crossover_arrivals:
                        cross_link_mal_ids.add(current_mal_id)
                    visited_ids.add(current_mal_id)
                    continue

                visited_ids.add(current_mal_id)

                if progress is not None:
                    discovered = len(visited_ids)
                    # Frontier has duplicates so this overshoots slightly
                    # but always converges to 100% as the queue drains.
                    await progress.update(
                        items_done=discovered,
                        items_total=discovered + len(left_mal_ids),
                    )

                if current_mal_id != mal_id:
                    anime_info = self.extract_information(await self.search_by_malid(current_mal_id))

                # Null-title sentinel: MAL leaves `title=null` on entries
                # it's still populating (romanization-pending donghua, PV
                # stubs). Blacklisting would block re-discovery once the
                # field fills in — skip without recording.
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
                    related_anime_graph[current_mal_id] = {
                        "mal_id": current_mal_id,
                        "title": anime_info["title"],
                        "aired_from": anime_info["aired_from"],
                        "media_type": anime_info["media_type"],
                    }

                    current_status = expand_by_mal_id.get(
                        current_mal_id, _ExpandStatus.TERMINAL,
                    )

                    # Crossover nodes are a franchise boundary — record
                    # the anime in the graph but don't BFS further.
                    # Without this, a single Fate × Tsukihime crossover
                    # collapses both franchises into one anime row.
                    #
                    # TERMINAL nodes (arrived via an identity-breaking
                    # edge — side_story / parent_story / summary /
                    # full_story / other / spin-off) are the v0.14.2
                    # boundary for cross-franchise contamination. Their
                    # outgoing edges ARE captured (so split-detection
                    # can see e.g. Vigilante's sequel chain leaking out
                    # of BNHA's row) but the BFS does NOT recurse from
                    # them — the queue-skip in the edge loop below keeps
                    # a chain of weak edges from bridging two franchises
                    # (Overlord → Eminence) or pulling the other
                    # franchise's full sequel chain into the graph.
                    if current_mal_id in crossover_arrivals:
                        all_related_media = []
                    elif current_mal_id in relation_cache:
                        # Anchor discovery (or an earlier BFS step) already
                        # fetched these — reuse to avoid the second MAL hit.
                        all_related_media = relation_cache[current_mal_id]
                    elif current_mal_id == mal_id and seed_payload is not None:
                        # The /full payload the dispatcher just fetched
                        # already bundles relations; reuse them.
                        all_related_media = seed_payload.get("relations") or []
                        relation_cache[current_mal_id] = all_related_media
                    else:
                        all_related_media = await self.fetch_relations(current_mal_id)
                        relation_cache[current_mal_id] = all_related_media

                    for target_mal_id, rel in parse_relation_edges(all_related_media):
                        edges.append((current_mal_id, target_mal_id, rel))
                        # TERMINAL parents capture outgoing edges (above)
                        # but don't queue targets — the graph stays
                        # bounded to nodes reachable from the seed via
                        # WALK propagation. Targets of TERMINAL edges
                        # land as dangling refs in MediaRelationEdges
                        # sidecars, same shape as cross-graph bridges,
                        # filtered defensively at _build_adjacency time.
                        if current_status is _ExpandStatus.TERMINAL:
                            continue
                        next_status = _next_expand_status(current_status, rel)
                        # Most-permissive wins so a side_story-then-sequel
                        # arrival from the same WALK parent doesn't get
                        # silently downgraded.
                        expand_by_mal_id[target_mal_id] = max(
                            expand_by_mal_id.get(target_mal_id, _ExpandStatus.TERMINAL),
                            next_status,
                        )
                        left_mal_ids.append(target_mal_id)
                        if rel == "crossover":
                            crossover_arrivals.add(target_mal_id)
                elif anime_info.get("airing_status") == AIRING_STATUS_NOT_YET_AIRED:
                    # Skip without blacklisting — MAL fills the type
                    # once the show airs.
                    logger.info(
                        "Skipping unscheduled anime without media_type: %s (mal_id=%s)",
                        anime_info.get("title"), current_mal_id,
                    )
                else:
                    logger.warning(f"Anime without media_type:\n{anime_info}")
                    unwanted_media.add((current_mal_id, anime_info["title"], "Unknown"))

            if related_anime_graph:
                sorted_graph = dict(
                    sorted(
                        related_anime_graph.items(),
                        key=lambda item: (item[1]["aired_from"] is None, item[1]["aired_from"]),
                    )
                )
                # Persist edges UNFILTERED, including targets outside
                # this anime's graph. When the same media later sits
                # inside a merge candidate, an originally-dangling
                # edge to the other side's media becomes the bridge
                # that re-connects the consolidated main chain — see
                # the Dr. Stone split-merge case in
                # tests/services/test_merge_candidate_service.py. The
                # classifier filters dangling endpoints defensively at
                # `_build_adjacency` so search-time + backfill-time
                # behavior is unchanged.
                relations.append((sorted_graph, edges, cross_link_mal_ids))

        return relations, all_info, unwanted_media
