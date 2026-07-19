import asyncio
import enum
import logging
import re
from collections import deque
from datetime import datetime, timezone
from time import monotonic
from typing import TYPE_CHECKING

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    wait_exponential,
)

from app.core.config import settings
from app.exceptions import AnimeNotFoundError, TransientUpstreamError
from app.services.relation_classifier import (
    AIRING_STATUS_NOT_YET_AIRED,
    anchor_tier,
    build_classifier_nodes,
    classify_anime_relations,
    would_be_dropped_as_weak_anchor,
)


def _is_transient_mal_error(exc: BaseException) -> bool:
    """5xx, 429, timeouts, and network errors are transient and worth
    retrying. Other 4xx (most importantly 404) is deterministic — same
    request will fail the same way, so burning exponential backoff
    just delays the inevitable failure.

    429 is special-cased BECAUSE the client-side rate limiter (1 req/s)
    leaves little headroom against MAL's undocumented ceiling: a brief
    burst overrun can produce 429 even though our average request rate is
    fine. Limited retry with backoff (capped at 3 attempts by
    _stop_strategy below) bridges a transient rejection. The tight cap is
    deliberate — if we're consistently 429'd, retrying harder masks
    sustained throttling instead of fixing it; the right response then is
    to slow the source rate (MAL_MIN_REQUEST_INTERVAL_S), not retry more."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))


def _stop_strategy(retry_state) -> bool:
    """Asymmetric retry budget: 3 total attempts for 429, 5 for
    everything else (5xx/timeouts/network). The lower 429 cap keeps a
    failing job from burning 31s+ of backoff when MAL is sustained-
    limiting us — 2 retries are enough to bridge a transient rejection;
    beyond that, retrying just delays the inevitable failure (and the job
    stays retryable=True so user-facing flows can re-submit from the
    bell)."""
    if retry_state.attempt_number >= 5:
        return True
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return retry_state.attempt_number >= 3
    return False

if TYPE_CHECKING:
    from app.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)

# The full field set requested on every anime detail fetch. MAL v2 returns
# nothing beyond id/title/main_picture unless `fields` names it explicitly.
# `related_anime` rides in the SAME response (node + relation_type +
# relation_type_formatted), so one detail call yields both the record AND its
# relations — the whole reason a BFS/sweep node now costs ONE MAL request
# instead of the two Jikan needed (/full + /relations).
_DETAIL_FIELDS = ",".join(
    [
        "id", "title", "alternative_titles", "main_picture",
        "start_date", "end_date", "synopsis", "mean", "num_scoring_users",
        "num_episodes", "media_type", "status", "genres", "source",
        "average_episode_duration", "rating", "start_season", "studios",
        "related_anime",
    ]
)

# Lean field set for MAL's LIST-style discovery endpoints (the title
# `/anime?q=` search + `/anime/season/{y}/{s}`). The q= SEARCH endpoint only
# ever returns lightweight node data and silently DROPS detail-only fields
# (most importantly `related_anime`) even when they're listed in `fields`, so
# the search is used purely as fuzzy title → mal_id discovery; every root's
# canonical data + relations come from a per-root detail fetch
# (search_by_malid). Requesting the full field set on a list endpoint would be
# misleading — it wouldn't come back. Seasonal discovery likewise needs only
# id + title (the dispatcher hands the title to a child scrape).
_SEARCH_FIELDS = "id,title"


# ---------------------------------------------------------------------------
# Value translation: MAL v2 emits snake_case / lowercase values where the
# catalog stores Jikan-era title-cased strings. Translating back on ingestion
# keeps the DB enums, the `ix_media_airing_now` partial index, the
# `age_rating_numeric` prefix map, the classifier sentinels, filter values,
# and every stored row untouched by the API swap (v0.14.14).
# ---------------------------------------------------------------------------

# Only the 6 INSERTABLE MediaType enum values need mapping — `music`/`cm`/`pv`
# are filtered by the skip-rule (which lowercases), and `unknown` maps to None
# so it falls through to the null-media_type handling.
_MEDIA_TYPE_MAP = {
    "tv": "TV",
    "movie": "Movie",
    "ova": "OVA",
    "ona": "ONA",
    "special": "Special",
    "tv_special": "TVSpecial",
    "unknown": None,
}

_AIRING_STATUS_MAP = {
    "currently_airing": "Currently Airing",
    "finished_airing": "Finished Airing",
    "not_yet_aired": "Not yet aired",
}

# MAL rating codes → the Jikan-style strings `Media.age_rating_numeric`
# prefix-matches (`PG-13`/`R+`/`R`/`PG`/`G`) and the filter surfaces.
_AGE_RATING_MAP = {
    "g": "G - All Ages",
    "pg": "PG - Children",
    "pg_13": "PG-13 - Teens 13 or older",
    "r": "R - 17+ (violence & profanity)",
    "r+": "R+ - Mild Nudity",
    "rx": "Rx - Hentai",
}

# MAL source enum → Jikan-style title case (filter-value + metadata-diff
# stability). Unknown values pass through unchanged rather than being dropped.
_SOURCE_MAP = {
    "other": "Other",
    "original": "Original",
    "manga": "Manga",
    "4_koma_manga": "4-koma manga",
    "web_manga": "Web manga",
    "digital_manga": "Digital manga",
    "novel": "Novel",
    "light_novel": "Light novel",
    "visual_novel": "Visual novel",
    "game": "Game",
    "card_game": "Card game",
    "book": "Book",
    "picture_book": "Picture book",
    "radio": "Radio",
    "music": "Music",
    "web_novel": "Web novel",
    "mixed_media": "Mixed media",
}


# The translated age_rating string MAL assigns to Hentai (see _AGE_RATING_MAP).
_AGE_RATING_HENTAI = _AGE_RATING_MAP["rx"]


def is_hentai(anime_info: dict) -> bool:
    """True when a MAL record is Hentai — either the explicit "Hentai" genre
    tag or the Rx age rating. Operates on `extract_information` output (the
    translated dict), so the fresh-scrape BFS skip and the nightly sweep's
    removal path reject the same content identically. The age-rating signal
    hardens against a record that carries the Rx rating but drops the genre
    tag."""
    genres = anime_info.get("genres") or []
    if any(name.lower() == "hentai" for name in genres):
        return True
    return anime_info.get("age_rating") == _AGE_RATING_HENTAI


def parse_mal_datetime(value: str | None) -> datetime | None:
    """Parse a full-ISO datetime string (as produced by `_mal_date_to_iso`
    and as stored in the catalog). None-safe. Kept as the shared parser the
    sweep dispatcher uses to compare `aired_from`/`aired_to` payload strings
    against the DB `DateTime` columns."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _mal_date_to_datetime(value: str | None) -> datetime | None:
    """Parse a MAL v2 date (`YYYY`, `YYYY-MM`, or `YYYY-MM-DD`) into a
    midnight-UTC datetime, filling a missing month/day with `01`. None-safe;
    returns None on a malformed value. The shared parser behind both
    `_mal_date_to_iso` (storage form) and the season derivation (needs the
    month) so the string isn't round-tripped through ISO to read it back."""
    if not value:
        return None
    parts = value.split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return datetime(year, month, day, tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None


def _mal_date_to_iso(value: str | None) -> str | None:
    """Normalize a MAL v2 date into the full midnight-UTC ISO string the
    catalog stores (`YYYY-MM-DDT00:00:00+00:00`).

    MAL drops Jikan's full ISO datetimes and emits partial dates for older /
    imprecise records. Filling the missing month/day with `01` at midnight UTC
    reproduces exactly how Jikan normalized these (verified: every stored
    aired_from/to is midnight UTC, year-only → 01-01), so a sweep re-fetch of
    an existing row doesn't spuriously diff the date."""
    dt = _mal_date_to_datetime(value)
    return dt.isoformat() if dt else None


def _month_to_season(month: int) -> str:
    """Month → MAL season name (lowercase — matches both the
    `/anime/season/{y}/{season}` URL segment and `start_season.season`).
    `.capitalize()` at the SeasonType-enum site."""
    if month <= 3:
        return "winter"
    if month <= 6:
        return "spring"
    if month <= 9:
        return "summer"
    return "fall"


# Relation labels MAL applies to identity-breaking derivatives. `spin_off` is
# aliased to the hyphenated form the existing catalog + docs use so a sweep
# re-fetch doesn't rewrite every spin-off sidecar edge. (MAL emits snake_case
# already, so the rest of `normalize_relation` is a near no-op — it stays as
# the single chokepoint every relation string flows through.)
_RELATION_ALIASES = {"spin_off": "spin-off"}


def normalize_relation(rel: str) -> str:
    """Normalize a MAL relation_type to the catalog's canonical form:
    lowercased, spaces → underscores, then the alias table (`spin_off` →
    `spin-off`). The single chokepoint so every downstream comparison uses
    one vocabulary."""
    norm = rel.lower().replace(" ", "_")
    return _RELATION_ALIASES.get(norm, norm)


# Relation labels excluded from edge capture: `character` is not a franchise
# membership signal (it's also where MAL routes cross-franchise collab links —
# the Isekai Quartet shape); `adaptation` and `alternative_setting` label
# cross-franchise links (manga adaptation, themed-shared but distinct shows) —
# walking them collapses distinct shows into one anime row.
_EXCLUDED_EDGE_RELS = frozenset({"character", "adaptation", "alternative_setting"})


# Relations that propagate "could be main chain of this graph" identity.
# Everything else MAL emits (side_story, parent_story, summary, full_story,
# other, spin-off) is identity-breaking: it connects related-but-distinct
# members. Without bounding the BFS at identity-breaking edges, a chain of
# weak edges (typically `other → other`) bridges two franchises — the
# Overlord → Eminence in Shadow regression caused by MAL labeling the
# `Ple Ple Pleiades x Kagejitsu!` collab special with relation `Other`.
# See tests/services/test_mal_scraper.py::
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


def parse_relation_edges(related_anime: list[dict]) -> list[tuple[int, str]]:
    """Project a MAL v2 `related_anime` list into
    `[(target_mal_id, normalized_rel), ...]`. Each entry is
    `{"node": {"id", ...}, "relation_type", "relation_type_formatted"}`.
    Applies the cross-franchise edge filter so callers don't re-implement it.
    `related_anime` contains anime only (manga lives in `related_manga`), so
    no per-entry type check is needed."""
    out: list[tuple[int, str]] = []
    for item in related_anime:
        rel = normalize_relation(item.get("relation_type", ""))
        if rel in _EXCLUDED_EDGE_RELS:
            continue
        node = item.get("node") or {}
        target = node.get("id")
        if target is not None:
            out.append((target, rel))
    return out


class MalScraper:
    # Client-side rate limiter. MAL's official-API limit is undocumented, but
    # ~1 req/s is safe in practice and matches the sustained ceiling that kept
    # the old Jikan mirror under 60/min. Because a v2 detail call bundles the
    # relations (one request per node instead of Jikan's two), effective
    # throughput already doubled — the interval is the conservative floor.
    # Lifted to settings so a policy change is an env tweak, not a rebuild.
    # Class-level so user_scrape and update_sweep share the gate if they
    # ever overlap.
    _MIN_REQUEST_INTERVAL_S: float = settings.MAL_MIN_REQUEST_INTERVAL_S
    _rate_lock: asyncio.Lock = asyncio.Lock()
    _last_request_at: float = 0.0

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.MAL_BASE_URL
        self.client: httpx.AsyncClient | None = None
        self.timeout = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)

    async def __aenter__(self):
        # Every MAL v2 request carries the client-id header; public data needs
        # no OAuth. The header is set on the client so it can't be forgotten
        # on an individual call.
        #
        # follow_redirects=True because MAL v2 intermittently answers a valid
        # `/anime/{id}` with a 307 Temporary Redirect (observed on ~1-2% of a
        # live sweep, on otherwise-fine ids like One Piece). httpx defaults to
        # NOT following redirects, and `raise_for_status()` treats an unfollowed
        # 3xx as an error — so without this a 307 surfaced as a non-retryable
        # step-1 failure (307 is neither 429 nor ≥500, so the retry predicate
        # skips it). Following the redirect resolves to the real 200 payload.
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            headers={"X-MAL-CLIENT-ID": settings.MY_ANIME_LIST_CLIENT_ID},
            follow_redirects=True,
        )
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
        # bridge a transient rejection), other transients at 5.
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
    def __get_anime_season(anime: dict) -> tuple[str | None, int | None]:
        start_season = anime.get("start_season") or {}
        season = start_season.get("season")
        year = start_season.get("year")
        if season and year:
            return season.capitalize(), int(year)

        # Fallback when MAL omits start_season: derive from the premiere date.
        date = _mal_date_to_datetime(anime.get("start_date"))
        if not date:
            return None, None
        return _month_to_season(date.month).capitalize(), date.year

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
            stripped = MalScraper._SYNOPSIS_CREDIT_TAG_RE.sub("", cleaned)
            if stripped == cleaned:
                break
            cleaned = stripped
        cleaned = cleaned.strip()
        return cleaned or None

    def extract_information(self, anime: dict) -> dict:
        alt_titles = anime.get("alternative_titles") or {}
        genres = [genre["name"] for genre in anime.get("genres", [])]
        anime_season_name, anime_season_year = MalScraper.__get_anime_season(anime)
        scored_by = anime.get("num_scoring_users") or 0
        media_type = anime.get("media_type")
        # Only the 6 insertable enum types translate; music/cm/pv pass through
        # (lowercase) for the skip-rule to filter; unknown → None.
        media_type = _MEDIA_TYPE_MAP.get(media_type, media_type)
        # average_episode_duration is already seconds — no string parsing. MAL
        # provides no human duration string, so the display column is dropped
        # (the frontend renders from duration_seconds via formatDuration).
        duration_seconds = anime.get("average_episode_duration") or None
        anime_id = anime.get("id")
        return {
            "mal_id": anime_id,
            "mal_url": f"https://myanimelist.net/anime/{anime_id}" if anime_id else None,
            "title": anime.get("title"),
            "name_eng": alt_titles.get("en") or None,
            "name_jap": alt_titles.get("ja") or None,
            "other_names": alt_titles.get("synonyms") or [],
            "media_type": media_type,
            "genres": genres,
            "studio": [studio["name"] for studio in anime.get("studios", [])],
            "age_rating": _AGE_RATING_MAP.get(anime.get("rating")),
            "description": MalScraper._clean_synopsis(anime.get("synopsis")),
            "original_source": _SOURCE_MAP.get(anime.get("source"), anime.get("source")),
            "cover_image": (anime.get("main_picture") or {}).get("large"),
            "score": anime.get("mean"),
            "scored_by": scored_by,
            "episodes": anime.get("num_episodes") or None,
            "anime_season_name": anime_season_name,
            "anime_season_year": anime_season_year,
            "aired_from": _mal_date_to_iso(anime.get("start_date")),
            "aired_to": _mal_date_to_iso(anime.get("end_date")),
            "airing_status": _AIRING_STATUS_MAP.get(anime.get("status"), anime.get("status")),
            "duration": None,
            "duration_seconds": duration_seconds,
        }

    async def fetch_relations(self, mal_id: int) -> list[dict]:
        """Fetch just the `related_anime` list for a mal_id. In v2 this is a
        detail call scoped to `related_anime` — used by the anchor-discovery
        pre-pass and the relation backfiller (main-BFS nodes reuse the
        relations bundled in their own detail fetch, so they never hit this)."""
        data = await self._get(
            f"{self.base_url}/anime/{mal_id}", params={"fields": "id,related_anime"},
        )
        return data.get("related_anime", [])

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

        Caches fetched relations into `relation_cache` so the main BFS
        doesn't re-fetch.
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
        """Fetch a single anime's full detail (fields + bundled related_anime).
        MAL v2 returns the object directly — no `data` envelope."""
        return await self._get(
            f"{self.base_url}/anime/{mal_id}", params={"fields": _DETAIL_FIELDS},
        )

    async def refresh_anime(self, mal_id: int) -> dict:
        """Alias for the sweep's step-1 refresh. In v2 a single detail call
        carries the volatile fields AND the `related_anime` block, so the
        step-2 probe can reuse the payload's relations without a second hit."""
        return await self.search_by_malid(mal_id)

    async def fetch_current_season(self) -> list[dict]:
        """Paginate the current season and return `[{"mal_id", "title"}, ...]`.

        MAL v2 has no `/seasons/now`; the current year+season is computed from
        the clock and passed to `/anime/season/{year}/{season}` sorted by
        popularity. Response shape: `{"data": [{"node": {...}}], "paging": {
        "next": <url|absent>}}`. The dispatcher only needs `mal_id` + `title`
        per entry — no `extract_information` here, the seasonal sweep just
        hands the title down to a child `user_scrape` job.
        """
        now = datetime.now(timezone.utc)
        season = _month_to_season(now.month)

        results: list[dict] = []
        offset = 0
        limit = 100
        while True:
            payload = await self._get(
                f"{self.base_url}/anime/season/{now.year}/{season}",
                params={
                    "sort": "anime_num_list_users",
                    "limit": limit,
                    "offset": offset,
                    "fields": _SEARCH_FIELDS,
                },
            )
            entries = payload.get("data", []) or []
            for entry in entries:
                node = entry.get("node") or {}
                results.append({"mal_id": node.get("id"), "title": node.get("title")})
            if not payload.get("paging", {}).get("next"):
                break
            offset += limit
        return results

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
        # relation_cache maps mal_id → its raw MAL `related_anime` list. Every
        # detail fetch (search root, anchor, or BFS node) bundles relations, so
        # populating the cache from each detail response means the main BFS
        # makes ONE MAL call per node instead of a separate /relations hit.
        relation_cache: dict[int, list[dict]] = {}

        if seed_mal_id is not None:
            # Probe path: skip the q= search; use the seed's own detail
            # payload (already in the dispatcher's hand) as the single
            # candidate. Subtract the seed from excluded_ids so the BFS
            # actually processes it instead of short-circuiting on
            # "already in catalog".
            seed_data = seed_payload or await self.search_by_malid(seed_mal_id)
            if not seed_data:
                # MAL returned 200 OK but an empty body — a real 404 would
                # have raised HTTPStatusError inside `_get`. This is a
                # transient MAL data hiccup (observed in practice: legitimate
                # mal_ids briefly return empty payloads). Use
                # TransientUpstreamError so the worker marks the job
                # retryable=True; otherwise a single cosmic-ray MAL response
                # permanently locks the mal_id out via the dedup window and
                # gets stamped as a Permanent failure that no one can retry.
                raise TransientUpstreamError(f"mal_id={seed_mal_id}")
            results = [seed_data]
            relation_cache[seed_mal_id] = seed_data.get("related_anime") or []
            excluded_ids: frozenset[int] = frozenset(excluded_mal_ids - {seed_mal_id})
        else:
            if title is None:
                raise ValueError("search_title requires either title or seed_mal_id")
            # Search is fuzzy title → mal_id discovery ONLY — the endpoint omits
            # related_anime (see _SEARCH_FIELDS), so we fetch each root's detail
            # below to get its relations. WITHOUT the detail fetch every root's
            # relation_cache stayed empty: the BFS captured no edges, never
            # walked the franchise, and each root saved as an isolated
            # single-media anime with an empty relation sidecar — the v0.14.14
            # regression that fragmented the catalog (Clannad/After Story/Movie
            # as 3 rows) and produced the spurious title_studio merge demotions.
            search = await self._get(
                f"{self.base_url}/anime",
                params={"q": title, "limit": initial_search_limit, "fields": _SEARCH_FIELDS},
            )
            candidate_ids = [
                entry["node"]["id"]
                for entry in search.get("data", [])
                if entry.get("node")
            ]
            if not candidate_ids:
                raise AnimeNotFoundError(title)
            # Fetch each root's full detail so its node data AND related_anime
            # are complete and consistent with every WALKED node (which the BFS
            # already fetches via search_by_malid). Populating relation_cache
            # here feeds BOTH the anchor-discovery pre-pass and the main BFS.
            results = []
            for candidate_id in candidate_ids:
                detail = await self.search_by_malid(candidate_id)
                if detail:
                    results.append(detail)
                    relation_cache[detail["id"]] = detail.get("related_anime") or []
            if not results:
                # Search matched but every hit's detail came back empty — a
                # transient MAL hiccup (a real 404 raises inside _get), not a
                # genuine miss. Retryable, mirroring the seed path above.
                raise TransientUpstreamError(
                    f"q={title!r}: all {len(candidate_ids)} search hits returned empty detail",
                )
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
        # original-seed iterations run.
        existing_mal_ids = {result["id"] for result in results}
        anchor_candidates: list[int] = []
        for result in results:
            discovered_anchors = await self._discover_anchors_upward(
                result["id"], excluded_ids, relation_cache,
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
                    relation_cache.setdefault(mal_id, payload.get("related_anime") or [])
            results = anchor_results + results

        # Process the canonical-est node first. `visited_ids` is shared
        # across iters, so if MAL's fuzzy search returns a non-canonical
        # entry first (Eva case: top hit `Evangelion: Chao Xianshi` ONA
        # has `other → Eva TV`, which would demote Eva TV to TERMINAL and
        # lock it out of iter 3 where Eva TV is the actual root), sorting
        # ensures the TV-shaped chain root walks the franchise BEFORE any
        # side-story-shaped result iter does.
        def _search_result_tier_sort(payload: dict) -> tuple:
            aired_from = _mal_date_to_iso(payload.get("start_date")) or ""
            return (anchor_tier(payload.get("media_type")), aired_from)

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

            while left_mal_ids:
                current_mal_id = left_mal_ids.popleft()

                if current_mal_id in visited_ids:
                    continue

                if current_mal_id in excluded_ids:
                    # Already in catalog. Crossings from the current graph into
                    # a catalog member become relation_link merge-candidate
                    # signals; the owning anime is resolved later in
                    # save_service.
                    if current_mal_id != mal_id:
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
                    raw = await self.search_by_malid(current_mal_id)
                    anime_info = self.extract_information(raw)
                    # Cache the relations bundled in this same detail response
                    # so the edge loop below doesn't pay a second MAL hit.
                    relation_cache.setdefault(current_mal_id, raw.get("related_anime") or [])

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

                # Hentai skip checked BEFORE the media_type gate so a hentai
                # record with a null media_type (rare, but MAL leaves the field
                # empty on freshly-announced titles) is still blacklisted rather
                # than falling through to the null-media_type anomaly branch.
                # is_hentai also matches the Rx age rating, not just the genre.
                if is_hentai(anime_info):
                    logger.warning(f"Skipping anime hentai: {anime_info['title']}")
                    unwanted_media.add((current_mal_id, anime_info["title"], "Hentai"))
                    continue

                if anime_info.get("media_type"):
                    if anime_info["media_type"].lower() in ["music", "pv", "cm"]:
                        logger.warning(f"Skipping anime {anime_info['media_type']}: {anime_info['title']}")
                        unwanted_media.add((current_mal_id, anime_info["title"], anime_info["media_type"]))
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

                    # TERMINAL nodes (arrived via an identity-breaking edge —
                    # side_story / parent_story / summary / full_story / other
                    # / spin-off) are the cross-franchise-contamination
                    # boundary. Their outgoing edges ARE captured (so
                    # split-detection can see e.g. Vigilante's sequel chain
                    # leaking out of BNHA's row) but the BFS does NOT recurse
                    # from them — the queue-skip in the edge loop below keeps a
                    # chain of weak edges from bridging two franchises
                    # (Overlord → Eminence) or pulling the other franchise's
                    # full sequel chain into the graph.
                    #
                    # One MAL call per node: relations rode in this node's own
                    # detail fetch and were cached there (or seeded from the
                    # root / anchor / seed payload), so every node reaching here
                    # is already in the cache — index directly.
                    all_related_media = relation_cache[current_mal_id]

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

            # Roll back visited_ids claims for any graph that save_service
            # would silently drop. Without this, a short-form franchise
            # whose first season is a search root (Isekai Quartet S1 —
            # 11-min TV with empty MAL relations) produces a 1-node
            # weak-anchor graph that gets dropped, but its mal_ids stay
            # claimed in visited_ids — the next root's BFS then skips
            # those mal_ids and the franchise loses that season
            # permanently. `would_be_dropped_as_weak_anchor` mirrors
            # search_service's actual skip predicate so the two sites
            # can't drift.
            if related_anime_graph:
                check_nodes = build_classifier_nodes(related_anime_graph, all_info)
                _, check_anchor = classify_anime_relations(check_nodes, edges)
                if would_be_dropped_as_weak_anchor(
                    check_nodes, check_anchor, seed_mal_id, cross_link_mal_ids,
                ):
                    # `visited_ids` is the only state that survives across
                    # root iterations and carries cross-root claims; the
                    # per-root locals (related_anime_graph, edges, etc.)
                    # fall out of scope naturally on `continue`.
                    for mid in related_anime_graph:
                        visited_ids.discard(mid)
                    continue

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
