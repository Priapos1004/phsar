"""The recommender's numerics: a user's natural history, the candidates and what picking one
commits to, the features a pooled conditional logit scores, the per-user calibrated row
(the slate) and each pick's reason. docs/features/recommender.md describes the whole.

Like `galaxy_compute`, whose `distances` it compares stars with, it imports nothing else
from the app: the rows arrive with the app's own definitions resolved
(`recommender_service.load_inputs`), so it can run in a spawned child and replay any past
moment.

The tuned constants below were measured on the prod data:
compound-docs/2026-11-12-v0.16.6-recommender.md.
"""

import hashlib
import math
from collections import defaultdict
from datetime import date, timedelta
from typing import NamedTuple

import numpy as np

from app.services.galaxy_compute import distances

# --- What counts as the user's own order --------------------------------------------------
# The implausible-day and import thresholds: docs/features/recommender.md, "The natural history".
IMPORT_MIN_ANIME = 5
WATCH_HOURS_PER_DAY = 16
IMPORT_GAP_DAYS = 14

# --- What picking an anime commits to ------------------------------------------------------
# The readiness rule's standalone line: docs/features/readiness.md, "The standalone rule".
STANDALONE_SECONDS = 20 * 3600
LENGTH_EDGES = (5, 15, 40)  # hours: the length buckets' edges
# A media's hours when MAL leaves a count out: the catalogue's median for its type.
MEDIAN_EPISODES = {"TV": 13, "ONA": 12, "Movie": 1, "Special": 1, "OVA": 1, "TVSpecial": 1}
MEDIAN_DURATION = {"TV": 1420, "Movie": 5160, "ONA": 641, "Special": 660, "OVA": 1500, "TVSpecial": 1441}
# Days from a commitment's finale to now that bound its freshness buckets (`finale_bucket`).
FINALE_EDGES = (-7, 30, 90, 365, 730)

# --- Features -------------------------------------------------------------------------------
LAGS = 3  # the last picks matched one by one
RECENT = 10  # the picks the decayed similarity reads
RECENT_HALF_LIFE = 3  # in picks
KNN = 20
FAVOURITE = 0.8  # own-percentile at or above which a rated anime is a favourite (top 20%)
PROPENSITY_HALF_LIFE = 10  # in picks, for the release-age, finale and length propensities
PROPENSITY_PRIOR = 2  # pseudo-picks pulling a propensity toward availability
DUE_PRIOR = 2  # pseudo-gaps pulling a facet's mean gap toward the facet's pooled gap
TREND_RECENT, TREND_BEFORE = 5, 10
LONG_HOURS = 10
# The intensity moderators' spread over the bake-off's decisions: the interactions are not
# standardised per decision, since the moderator is the same for every candidate.
LOAD_MEAN, LOAD_SD = -0.1291, 0.8036
LONG_MEAN, LONG_SD = 3.7243, 0.9476

# --- The row --------------------------------------------------------------------------------
ROW = 25  # the Home row's length, and the window the caps and slots apply to
EXPLORE_SLOTS = (8, 16, 24)  # 1-based positions in each window of ROW
REGION_CAP = 3  # tiles per galaxy region in each window
EXPLORE_COVERAGE = 1 / 3  # regions in the user's least-covered third feed the explore slots
CAP_PRIOR = 20  # pseudo-picks pulling a user's pick mix toward the pooled one
POOLED_LISTED = 0.68  # share of natural picks that were listed (the prod dumps' reconstruction)
POOLED_CONTINUATION = 0.23  # share of natural picks that continued a started anime
ALPHA = 0.5  # the enjoyment tilt: score + ALPHA · z(kNN own-percentile)

NAMES: tuple[str, ...] = (
    "F1_sim_lag1", "F1_sim_lag2", "F1_sim_lag3", "F1_sim_decay10",
    *(f"F2_{facet}_lag{k}" for k in range(1, LAGS + 1)
      for facet in ("sector", "region", "genreJac", "studio", "len", "age")),
    "F3_due_sector_ev", "F3_due_sector_days", "F3_never_sector",
    "F3_due_region_ev", "F3_due_region_days", "F3_never_region",
    "F3_due_len_ev", "F3_due_len_days", "F3_never_len",
    "F3_due_age_ev", "F3_due_age_days", "F3_never_age",
    "F3_never_genre", "F3_due_genre_ev", "F3_due_genre_days",
    "F4_trend_sector", "F4_trend_len", "F4_trend_genre",
    "F5_knn_pct", "F5_top20_sim", "F5_mal", "F5_mal_missing", "F5_logvotes",
    "F6_loglen", "F6_long",
    "F7_is_cont", "F7_own_pct", "F7_log_days_since",
    "F8_age_propensity",
    "F6_loglen_x_load", "F6_long_x_days",
    "F9_len_propensity", "W_p1", "W_p2", "W_p3", "W_log_age", "W_backlog",
    "F10_finale_propensity",
)
COLUMN = {name: i for i, name in enumerate(NAMES)}


def family(name: str) -> str:
    return "F6x" if "_x_" in name else name.split("_")[0]


HARNESS = ("F3", "F4", "F6x")  # what `decide(harness=True)` adds: measured, never ranked
# The intensity interactions are already scaled; which features stay raw and why:
# docs/features/recommender.md, "The ranking".
SCALED = np.array([family(name) not in ("F6x", "W") for name in NAMES])

# What a feature says about a pick, when its group contributes the most to its score. A group
# absent from this map never leads a reason.
REASON_OF = {
    "F1": "recent", "F2": "recent", "F5_top20_sim": "favourite", "F5_mal": "popular",
    "F5_mal_missing": "popular", "F5_logvotes": "popular",
    "F8": "fresh", "F10": "fresh", "W": "watchlist",
}
_REASON_COLUMNS: dict[str, list[int]] = defaultdict(list)
for _name, _j in COLUMN.items():
    _kind = REASON_OF.get(_name) or REASON_OF.get(_name.split("_")[0])
    if _kind:
        _REASON_COLUMNS[_kind].append(_j)

# The reviewed output of `scripts/backtest_recommender.py --fit --dumps`; its keys are what ranks.
# Which features stay out and why: docs/features/recommender.md, "The ranking"; the compound doc
# has its numbers.
WEIGHTS: dict[str, float] = {
    "F1_sim_decay10": 0.33, "F2_sector_lag1": -0.11, "F2_region_lag1": 0.06, "F2_genreJac_lag1": 0.17,
    "F2_studio_lag1": 0.13, "F2_len_lag1": 0.01, "F2_age_lag1": 0.1, "F5_knn_pct": -0.24,
    "F5_top20_sim": 0.65, "F5_mal": -0.09, "F5_mal_missing": -0.14, "F5_logvotes": 0.45,
    "F6_loglen": -0.13, "F6_long": -0.24, "F7_is_cont": 0.06, "F8_age_propensity": 0.23,
    "F9_len_propensity": 0.22, "W_p1": 0.57, "W_p2": 0.11, "W_p3": -0.31, "W_log_age": 0.08,
    "W_backlog": 0.77, "F10_finale_propensity": 0.43,
}

VERSION = 1
EPOCH = date(1970, 1, 1)
DAY = 86400.0


def version() -> str:
    """What a ranking is computed with: `VERSION` and every module constant, the weights
    included."""
    constants = sorted((k, repr(v)) for k, v in globals().items() if k.isupper())
    return f"{VERSION}-{hashlib.sha256(repr(constants).encode()).hexdigest()[:12]}"


# --- Rows in ----------------------------------------------------------------------------------

class MediaRow(NamedTuple):
    media_id: int
    anime_id: int
    mal_id: int
    main: bool  # in `MAIN_STORY_RELATIONS`
    media_type: str
    episodes: int | None
    duration_seconds: int | None
    total_watch_time: int | None  # `Media.total_watch_time`
    season_year: int | None
    season_name: str | None
    season_key: int | None  # `search_filters.SEASON_KEY`
    aired_from: date | None
    aired_to: date | None
    unaired: bool  # airing_status is "Not yet aired"
    airing: bool  # airing_status is "Currently Airing"


class StarRow(NamedTuple):
    anime_id: int
    features: list[float]
    uncertainty: float
    sector: int
    region: int
    score: float | None  # the anime's MAL score and votes, as the app shows them
    votes: float | None
    genres: tuple[str, ...]  # its majority genres and themes
    studios: tuple[str, ...]  # behind its main story


class RatingRow(NamedTuple):
    media_id: int
    rating: float
    status: str  # a `WatchStatus` value
    created_at: float  # epoch seconds
    watched_at: float | None  # the first watch event, epoch seconds
    episodes_watched: int | None


class ListingRow(NamedTuple):
    """One stretch of a watchlist entry at one priority. A live entry runs from its last
    change to now (`until` None); history rebuilt from the dumps splits an entry at each
    change and ends it where it left the list."""
    media_id: int
    priority: int
    since: float  # listed, or last changed
    until: float | None
    tag: str | None = None  # the list's name


def listings_from_log(events: list[tuple[int, str, int, str | None, float]]) -> list[ListingRow]:
    """Each entry's stretches from the watchlist's log, `(media_id, kind, priority, tag, at)` in
    order: an add or a change opens one, closing the one before, and a removal closes it."""
    current: dict[int, tuple[int, float, str | None]] = {}
    out = []
    for media_id, kind, priority, tag, at in events:
        if media_id in current:
            prio, since, list_ = current.pop(media_id)
            out.append(ListingRow(media_id, prio, since, at, list_))
        if kind != "removed":
            current[media_id] = (priority, at, tag)
    out.extend(ListingRow(m, prio, since, None, list_) for m, (prio, since, list_) in current.items())
    return out


class Pick(NamedTuple):
    anime_id: int
    rank: int
    kind: str
    ref_anime_id: int | None
    detail: str | None


# --- Time ---------------------------------------------------------------------------------------

def _day(t: float) -> int:
    return math.floor(t / DAY)


def _quarter_start(day: int) -> int:
    d = EPOCH + timedelta(days=day)
    return (date(d.year, 3 * ((d.month - 1) // 3) + 1, 1) - EPOCH).days


def _start_day(m: MediaRow) -> float:
    """The day a media's season starts, else the day it aired, else NaN."""
    if m.season_key:
        year, rank = divmod(m.season_key, 10)
        return float((date(year, 3 * rank - 2, 1) - EPOCH).days)
    return float((m.aired_from - EPOCH).days) if m.aired_from else math.nan


def _finale_day(m: MediaRow) -> float:
    """The day a media's last episode airs: its end date, else for an airing season a week
    per episode after its start (inf when even that is unknown), else the day it aired."""
    if m.aired_to:
        return float((m.aired_to - EPOCH).days)
    if m.airing:
        if m.aired_from and m.episodes:
            return float((m.aired_from - EPOCH).days + 7 * (m.episodes - 1))
        return math.inf
    return float((m.aired_from - EPOCH).days) if m.aired_from else math.nan


def age_bucket(start: np.ndarray, t: float) -> np.ndarray:
    """How long before `t` a season started: 0 this season (a future start included), 1 last
    season, then up to 2, 5 and 10 years, 5 older, 6 unknown. Seasons are calendar quarters."""
    today = _day(t)
    this = _quarter_start(today)
    last = _quarter_start(this - 1)
    age = today - start
    with np.errstate(invalid="ignore"):
        return np.select(
            [np.isnan(start), start >= this, start >= last, age <= 730, age <= 1826, age <= 3652],
            [6, 0, 1, 2, 3, 4], default=5,
        ).astype(np.int64)


def length_bucket(hours: np.ndarray) -> np.ndarray:
    return np.digitize(hours, LENGTH_EDGES).astype(np.int64)


def finale_bucket(finale: np.ndarray, t: float) -> np.ndarray:
    """How fresh a commitment is by its finale (`FINALE_EDGES`): 0 airing with the finale
    over a week ahead, 1 finale week to a month after, … 5 older, 6 unknown."""
    since = _day(t) - finale
    bucket = np.digitize(since, FINALE_EDGES, right=True).astype(np.int64)
    return np.where(np.isnan(since), len(FINALE_EDGES) + 1, bucket)


# --- The catalogue -------------------------------------------------------------------------------

class Catalogue(NamedTuple):
    """Every star with the facts the features read, and every media of a starred anime in
    (anime, chronological) order. Built once per recompute from the DAO's rows."""
    anime_id: np.ndarray
    row_of: dict[int, int]
    features: np.ndarray
    uncertainty: np.ndarray
    sector: np.ndarray
    region: np.ndarray
    mal: np.ndarray
    mal_missing: np.ndarray
    votes: np.ndarray  # log1p
    genres: np.ndarray  # (anime, genre) bool
    studios: np.ndarray  # (anime, studio) bool
    position_of: dict[int, int]
    media_row: np.ndarray
    main: np.ndarray
    hours: np.ndarray  # imputed where MAL leaves a count out
    raw_episodes: np.ndarray  # NaN when unknown
    raw_duration: np.ndarray
    standalone: np.ndarray
    start: np.ndarray  # day, NaN when unknown
    finale: np.ndarray  # day its last episode airs, inf while airing with no end in sight
    aired_day: np.ndarray  # NaN when no air date
    unaired: np.ndarray
    ready: list["ReadyItem"]  # each media's readiness facts, its watch status left to the user
    main_of: list[list[int]]  # per star, its main-story media positions


def catalogue(stars: list[StarRow], media: list[MediaRow], chronological) -> Catalogue:
    """`chronological(season_year, season_name, mal_id)` is the project's media order
    (`filter_service.chronological_media_key`), passed in so this module stays app-free."""
    row_of = {s.anime_id: i for i, s in enumerate(stars)}
    media = sorted(
        (m for m in media if m.anime_id in row_of),
        key=lambda m: (row_of[m.anime_id], chronological(m.season_year, m.season_name, m.mal_id)),
    )
    n = len(stars)
    rows = np.array([row_of[m.anime_id] for m in media], dtype=np.int64)
    main = np.array([m.main for m in media], dtype=bool)
    hours = np.array([
        (m.episodes or MEDIAN_EPISODES.get(m.media_type, 1))
        * (m.duration_seconds or MEDIAN_DURATION.get(m.media_type, 1)) / 3600
        for m in media
    ])
    genre_col = {g: i for i, g in enumerate(sorted({g for s in stars for g in s.genres}))}
    studio_col = {s: i for i, s in enumerate(sorted({x for s in stars for x in s.studios}))}
    genres = np.zeros((n, len(genre_col)), dtype=bool)
    studios = np.zeros((n, len(studio_col)), dtype=bool)
    for r, s in enumerate(stars):
        genres[r, [genre_col[g] for g in s.genres]] = True
        studios[r, [studio_col[x] for x in s.studios]] = True
    mal = np.array([math.nan if s.score is None else s.score for s in stars], dtype=float)
    mal_missing = np.isnan(mal)
    mal[mal_missing] = np.nanmean(mal) if (~mal_missing).any() else 0.0
    main_of: list[list[int]] = [[] for _ in range(n)]
    for p in np.flatnonzero(main).tolist():
        main_of[rows[p]].append(p)
    return Catalogue(
        anime_id=np.array([s.anime_id for s in stars], dtype=np.int64), row_of=row_of,
        features=np.array([s.features for s in stars], dtype=np.float64) if n else np.zeros((0, 0)),
        uncertainty=np.array([s.uncertainty for s in stars], dtype=np.float64),
        sector=np.array([s.sector for s in stars], dtype=np.int64),
        region=np.array([s.region for s in stars], dtype=np.int64),
        mal=mal, mal_missing=mal_missing.astype(float),
        votes=np.log1p(np.array([s.votes or 0.0 for s in stars], dtype=float)),
        genres=genres, studios=studios,
        position_of={m.media_id: i for i, m in enumerate(media)},
        media_row=rows, main=main, hours=hours,
        raw_episodes=np.array([m.episodes or math.nan for m in media], dtype=float),
        raw_duration=np.array([m.duration_seconds or math.nan for m in media], dtype=float),
        standalone=np.array([(m.total_watch_time or 0) >= STANDALONE_SECONDS for m in media], dtype=bool),
        start=np.array([_start_day(m) for m in media]),
        finale=np.array([_finale_day(m) for m in media]),
        aired_day=np.array([float((m.aired_from - EPOCH).days) if m.aired_from else math.nan for m in media]),
        unaired=np.array([m.unaired for m in media], dtype=bool),
        ready=[
            ReadyItem(m.main, "airing" if m.airing else "unaired" if m.unaired else "aired",
                      m.season_key, None, m.total_watch_time)
            for m in media
        ],
        main_of=main_of,
    )


# --- A user's history --------------------------------------------------------------------------

class Event(NamedTuple):
    """A natural anime event: one anime's media first watched on one day."""
    t: float
    row: int
    hours: float
    rating: float  # the mean of its media's ratings, for the backtest's liked picks
    media: tuple[int, ...]  # catalogue positions


class Ledger(NamedTuple):
    """One user's history, prepared once: every rated media with its event time, the
    natural events in order, each natural pick's own state, the watchlist's stretches and
    the franchise signals the readiness verdict reads."""
    position: np.ndarray  # catalogue position of each rated media
    t: np.ndarray  # its event time
    rating: np.ndarray
    status: np.ndarray  # each rated media's `WatchStatus` value
    natural: list[Event]
    start: int | None  # the first natural day
    pick_length: np.ndarray  # each natural pick's length, release-age and finale bucket at its
    pick_age: np.ndarray  # time, and whether it continued a started anime
    pick_finale: np.ndarray
    pick_cont: np.ndarray
    listed: list[tuple[int, int, float, float, str | None]]  # (position, priority, since, until, tag)
    pick_listed: np.ndarray  # whether each natural pick was listed at the time, NaN when unknown
    listed_from: float  # when `listed` starts to hold the whole history, inf when it never does
    franchise: dict[int, tuple[bool, int | None]]  # per star: `franchise_signals`


def event_time(r: RatingRow) -> float:
    """When the user finished a media: its first watch event when completed (an
    on_hold → completed edit counts when it was finished), else when it was rated."""
    return r.watched_at if r.status == "completed" and r.watched_at is not None else r.created_at


def natural_days(days: dict[int, tuple[float, int]], override: int | None) -> tuple[set[int], int | None]:
    """Which of the rating days (day → (hours, distinct anime)) are natural, and the first
    natural day. docs/features/recommender.md, "The natural history", gives the rule."""
    order = sorted(days)
    implausible: list[int] = []
    previous = None
    for d in order:
        hours, anime = days[d]
        gap = 1 if previous is None else d - previous
        if anime >= IMPORT_MIN_ANIME and hours > WATCH_HOURS_PER_DAY * gap:
            implausible.append(d)
        previous = d
    if override is not None:
        start = override
    else:
        start = None
        if implausible and implausible[0] - order[0] < IMPORT_GAP_DAYS:
            end = implausible[0]
            for d in implausible[1:]:
                if d - end >= IMPORT_GAP_DAYS:
                    break
                end = d
            start = end + 1
    first = order[0] if start is None and order else start
    skip = set(implausible)
    return {d for d in order if d >= first and d not in skip} if first is not None else set(), first


def ledger(
    cat: Catalogue, ratings: list[RatingRow], listings: list[ListingRow],
    override: date | None = None, franchise: dict[int, tuple[bool, int | None]] | None = None,
    listed_from: float = math.inf,
) -> Ledger:
    """`franchise` maps anime ids to `franchise_signals`; the backtest replays them as they
    stand today. `listed_from` is when `listings` start to hold the whole watchlist history:
    a pick before it, or with no such history, has an unknown listing."""
    rated = [r for r in ratings if r.media_id in cat.position_of]
    position = np.array([cat.position_of[r.media_id] for r in rated], dtype=np.int64)
    t = np.array([event_time(r) for r in rated], dtype=float)
    watched = np.array([np.nan if r.episodes_watched is None else r.episodes_watched for r in rated], dtype=float)
    hours = np.nan_to_num(np.where(np.isnan(watched), cat.raw_episodes[position], watched)) * np.nan_to_num(
        cat.raw_duration[position]) / 3600
    day_of = np.floor(t / DAY).astype(np.int64).tolist()
    row_of = cat.media_row[position].tolist()
    days: dict[int, list] = defaultdict(lambda: [0.0, set()])
    for i, d in enumerate(day_of):
        days[d][0] += hours[i]
        days[d][1].add(row_of[i])
    natural, start = natural_days(
        {d: (h, len(a)) for d, (h, a) in days.items()},
        (override - EPOCH).days if override else None,
    )
    grouped: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, d in enumerate(day_of):
        if d in natural:
            grouped[(row_of[i], d)].append(i)
    ratings_ = np.array([r.rating for r in rated], dtype=float)
    events = sorted(
        Event(t=float(t[ix].min()), row=row, hours=float(hours[ix].sum()),
              rating=float(ratings_[ix].mean()), media=tuple(position[ix].tolist()))
        for (row, _), ix in grouped.items()
    )
    status = np.array([r.status for r in rated], dtype="U9")
    lengths, ages, finales, conts = [], [], [], []
    for e in events:
        before = t < e.t
        s = state(cat, e.t, position[before], status[before])
        if s.candidate[e.row]:
            span = (s.hours[e.row], s.start[e.row], s.finale[e.row])
        else:
            own = list(e.media)
            span = (e.hours, np.fmin.reduce(cat.start[own]), np.fmax.reduce(cat.finale[own]))
        lengths.append(int(length_bucket(np.array([span[0]]))[0]))
        ages.append(int(age_bucket(np.array([span[1]]), e.t)[0]))
        finales.append(int(finale_bucket(np.array([span[2]]), e.t)[0]))
        conts.append(bool(s.continuation[e.row]))
    listed = [
        (cat.position_of[x.media_id], x.priority, x.since, math.inf if x.until is None else x.until, x.tag)
        for x in listings if x.media_id in cat.position_of
    ]
    # Every stretch for every pick since the log began: index the stretches by anime if a long
    # log ever makes this show in a recompute.
    pick_listed = np.array([
        float(any(cat.media_row[p] == e.row for p, *_ in _active(listed, listed_from, e.t))) if e.t >= listed_from
        else math.nan
        for e in events
    ])
    return Ledger(
        position=position, t=t, rating=ratings_, status=status, natural=events, start=start,
        pick_length=np.array(lengths, dtype=np.int64), pick_age=np.array(ages, dtype=np.int64),
        pick_finale=np.array(finales, dtype=np.int64),
        pick_cont=np.array(conts, dtype=bool), listed=listed, pick_listed=pick_listed, listed_from=listed_from,
        franchise={cat.row_of[a]: v for a, v in (franchise or {}).items() if a in cat.row_of},
    )


def _active(listed: list, listed_from: float, t: float) -> list[tuple[int, int, float, str | None]]:
    """The stretches on the list at `t`: none before `listed_from`, docs/features/recommender.md,
    "The ranking"."""
    if t < listed_from:
        return []
    return [(p, prio, since, tag) for p, prio, since, until, tag in listed if since <= t < until]


def listing(cat: Catalogue, led: Ledger, t: float) -> tuple[list[tuple[int, int, float, str | None]], np.ndarray, np.ndarray]:
    """The watchlist at `t`: its stretches then active (position, priority, since, tag), and
    per star the best priority (0 when unlisted) and when it was last listed or changed."""
    active = _active(led.listed, led.listed_from, t)
    priority = np.zeros(len(cat.anime_id), dtype=np.int64)
    touched = np.full(len(cat.anime_id), -math.inf)
    for p, prio, since, _ in active:
        r = cat.media_row[p]
        priority[r] = prio if priority[r] == 0 else min(priority[r], prio)
        touched[r] = max(touched[r], since)
    return active, priority, touched


# --- Can it be started tonight? ----------------------------------------------------------------
# The watchlist's readiness verdict, in the backend for the recommender:
# docs/features/readiness.md, "Where it is computed".

class ReadyItem(NamedTuple):
    """One media of the selection the verdict reads (`_verdicts` chooses it)."""
    main: bool
    phase: str  # "aired" | "airing" | "unaired"
    season_key: int | None
    watch_status: str | None
    total_watch_time: int | None


def next_season_key(t: float) -> int:
    """The `SEASON_KEY` of the season after the one `t` falls in; Fall rolls into the next
    Winter."""
    d = EPOCH + timedelta(days=_day(t))
    following = ((d.month - 1) // 3 + 1) % 4  # Fall wraps to 0
    return (d.year + (following == 0)) * 10 + following + 1


def media_class(item: ReadyItem, next_key: int) -> str:
    """aired, airing, soon (unaired, next season or earlier), later, or tba."""
    if item.phase != "unaired":
        return item.phase
    if item.season_key is None:
        return "tba"
    return "soon" if item.season_key <= next_key else "later"


def something_to_watch(items: list[ReadyItem], next_key: int) -> bool:
    """Test A of docs/features/readiness.md, "The verdict" — on its own because the
    recommender applies it whatever the verdict."""
    classes = [media_class(i, next_key) for i in items]
    waiting_on_unaired = any(c in ("soon", "later", "tba") for c in classes)
    return not waiting_on_unaired or any(
        c == "aired" and i.watch_status != "completed" for i, c in zip(items, classes, strict=True)
    )


def readiness(items: list[ReadyItem], franchise_airing: bool, franchise_upcoming_key: int | None, next_key: int) -> str:
    """ready, standalone, hot or waiting: tests A, B1 and B2 and the standalone rule."""
    classes = [media_class(i, next_key) for i in items]
    governing = [c for i, c in zip(items, classes, strict=True) if i.main] or classes
    nothing_listed_pending = not any(c in ("airing", "soon") for c in governing)
    franchise_blocks = franchise_airing or (franchise_upcoming_key is not None and franchise_upcoming_key <= next_key)
    standalone = franchise_blocks and any((i.total_watch_time or 0) >= STANDALONE_SECONDS for i in items)
    if not nothing_listed_pending or (franchise_blocks and not standalone):
        return "hot"
    if not something_to_watch(items, next_key):
        return "waiting"
    return "standalone" if standalone else "ready"


def _verdicts(
    cat: Catalogue, C: np.ndarray, led: Ledger, listed: np.ndarray, planned: np.ndarray, status_of: dict[int, str], t: float,
) -> np.ndarray:
    """Each candidate's verdict, as docs/features/recommender.md, "Candidates", gives it."""
    selection: dict[int, list[int]] = defaultdict(list)
    for p in listed.tolist():
        selection[int(cat.media_row[p])].append(p)
    next_key = next_season_key(t)
    out = []
    for r in C.tolist():
        items = [cat.ready[p]._replace(watch_status=status_of.get(p)) for p in (selection[r] if planned[r] else cat.main_of[r])]
        out.append(readiness(items, *led.franchise.get(r, (False, None)), next_key) if something_to_watch(items, next_key) else "waiting")
    return np.array(out, dtype="U10")


# --- What can be picked at a moment ---------------------------------------------------------------

class State(NamedTuple):
    candidate: np.ndarray  # per star
    continuation: np.ndarray
    planned: np.ndarray  # some listed media has aired: the list, not the main story, is the commitment
    hours: np.ndarray  # what picking it commits to
    start: np.ndarray  # the day that commitment's earliest season starts, NaN when unknown
    finale: np.ndarray  # the day its last season ends


def state(
    cat: Catalogue, t: float, rated: np.ndarray, status: np.ndarray, listed: np.ndarray | None = None,
) -> State:
    """Each star's standing at `t`, from the media rated before it (`rated`, catalogue
    positions, with each one's `status`) and the media listed at it. Who is a candidate:
    docs/features/recommender.md, "Candidates"."""
    n, day = len(cat.anime_id), _day(t)
    aired = np.where(np.isnan(cat.aired_day), ~cat.unaired, cat.aired_day <= day)
    aired_main = cat.main & aired

    def flag(positions: np.ndarray) -> np.ndarray:
        mask = np.zeros(len(cat.media_row), dtype=bool)
        mask[positions] = True
        return mask

    def per_star(mask: np.ndarray) -> np.ndarray:
        return np.bincount(cat.media_row[mask], minlength=n)

    unwatched = aired_main & ~flag(rated[status == "completed"])
    touched = per_star(flag(rated)) > 0
    has_main = per_star(aired_main) > 0
    dropped_main = per_star(cat.main & flag(rated[status == "dropped"])) > 0
    continuation = touched & ~dropped_main & (per_star(unwatched) > 0)
    candidate = (has_main & ~touched) | continuation
    commit = unwatched
    planned = np.zeros(n, dtype=bool)
    if listed is not None:
        on_list = flag(listed) & aired
        planned = per_star(on_list) > 0
        candidate = candidate | (planned & has_main)
        commit = np.where(planned[cat.media_row], on_list, unwatched)
    return State(candidate, continuation, planned, *_commitment(cat, commit, n))


def _commitment(cat: Catalogue, mask: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per star, the hours, earliest start and last finale of the media picking it starts:
    walking its masked media in order, everything up to the first standalone media, or that
    media alone when it comes first."""
    idx = np.flatnonzero(mask)
    hours = np.zeros(n)
    if not len(idx):
        return hours, np.full(n, math.nan), np.full(n, math.nan)
    rows = cat.media_row[idx]
    alone = cat.standalone[idx]
    first = np.r_[True, rows[1:] != rows[:-1]]
    seen = np.cumsum(alone)
    before_group = np.maximum.accumulate(np.where(first, seen - alone, 0))
    opens_alone = alone[first][np.cumsum(first) - 1]
    take = first | (~opens_alone & (seen - before_group == 0))
    np.add.at(hours, rows[take], cat.hours[idx][take])
    start, finale = np.full(n, math.nan), np.full(n, math.nan)
    np.fmin.at(start, rows[take], cat.start[idx][take])
    np.fmax.at(finale, rows[take], cat.finale[idx][take])
    return hours, start, finale


# --- Features ------------------------------------------------------------------------------------------

class Decision(NamedTuple):
    rows: np.ndarray  # the candidates' star rows
    X: np.ndarray  # (candidates, features), standardised
    raw_knn: np.ndarray  # own-percentile kNN, for the explore slots
    listed: np.ndarray  # per candidate
    priority: np.ndarray  # best active priority, 0 when unlisted
    continuation: np.ndarray
    nearest_recent: np.ndarray  # star row of the recent pick nearest each candidate, -1 if none
    nearest_favourite: np.ndarray
    coverage: np.ndarray  # per star: the user's share of rated anime in its region


def _rank(x: np.ndarray) -> np.ndarray:
    """1-based ranks, ties averaged — `scipy.stats.rankdata`'s default, kept here because
    importing `scipy.stats` costs ~0.5 s on the first request a process serves."""
    _, inverse, counts = np.unique(x, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    return (ends - (counts - 1) / 2)[inverse]


def _simrank(x: np.ndarray) -> np.ndarray:
    """1 for the nearest candidate down to 0 for the farthest, ties averaged."""
    if len(x) < 2:
        return np.zeros(len(x))
    return 1 - (_rank(x) - 1) / (len(x) - 1)


def _propensity(history: np.ndarray, current: np.ndarray, buckets: int) -> np.ndarray:
    """How much more than availability the user's recent picks favour each candidate's
    bucket: recency-weighted shares, pulled toward availability, over availability."""
    available = np.bincount(current, minlength=buckets) / max(len(current), 1)
    if not len(history):
        return np.zeros(len(current))
    weights = 0.5 ** (np.arange(len(history)) / PROPENSITY_HALF_LIFE)
    picked = np.bincount(history[::-1], weights=weights, minlength=buckets)
    share = (picked + PROPENSITY_PRIOR * available) / (weights.sum() + PROPENSITY_PRIOR)
    return np.log(np.maximum(share, 1e-9) / np.maximum(available, 1e-9))[current]


def _due(values: list[list[int]], times: np.ndarray, t: float, candidate: list[list[int]]) -> tuple:
    """Events and days since the user last picked each candidate's value of one facet,
    over that value's usual gap (pulled toward the facet's pooled gap), and whether they
    never did. Harness only. `values[i]` are pick i's values,
    `candidate[c]` candidate c's; the max over a candidate's values is taken."""
    nh = len(values)
    at: dict[int, list[int]] = defaultdict(list)
    for i, vs in enumerate(values):
        for v in set(vs):
            at[v].append(i)
    gaps_ev = [g for js in at.values() for g in np.diff(js)]
    gaps_day = [g for js in at.values() for g in np.diff(times[js]) / DAY]
    pooled_ev = float(np.mean(gaps_ev)) if gaps_ev else float(nh)
    pooled_day = float(np.mean(gaps_day)) if gaps_day else (t - times[0]) / DAY if nh else 1.0
    score: dict[int, tuple[float, float]] = {}
    for v, js in at.items():
        d_ev, d_day = np.diff(js), np.diff(times[js]) / DAY
        mean_ev = (d_ev.sum() + DUE_PRIOR * pooled_ev) / (len(d_ev) + DUE_PRIOR)
        mean_day = max((d_day.sum() + DUE_PRIOR * pooled_day) / (len(d_day) + DUE_PRIOR), 0.5)
        score[v] = (math.log1p((nh - js[-1]) / mean_ev), math.log1p((t - times[js[-1]]) / DAY / mean_day))
    out = np.full((len(candidate), 3), [math.log(2), math.log(2), 1.0])
    for c, own in enumerate(candidate):
        hits = [score[v] for v in own if v in score]
        if hits:
            out[c] = [max(h[0] for h in hits), max(h[1] for h in hits), 0.0]
    return out[:, 0], out[:, 1], out[:, 2]


def decide(cat: Catalogue, led: Ledger, t: float, *, hot: bool = True, harness: bool = False) -> Decision:
    """The candidates at `t` and their features, from the history before it. Who is one:
    docs/features/recommender.md, "Candidates". `harness` also computes the families the
    ranking doesn't read."""
    before = led.t < t
    rated, status = led.position[before], led.status[before]
    dropped = status == "dropped"
    listed_now, priority, touched = listing(cat, led, t)
    listed_positions = np.array([p for p, *_ in listed_now], dtype=np.int64)
    s = state(cat, t, rated, status, listed_positions)
    C = np.flatnonzero(s.candidate)
    verdicts = _verdicts(cat, C, led, listed_positions, s.planned, dict(zip(rated.tolist(), status.tolist(), strict=True)), t)
    C = C[(verdicts != "waiting") & (hot | (verdicts != "hot"))]
    n = len(C)
    X = np.zeros((n, len(NAMES)))
    if not n:
        empty = np.zeros(0, dtype=np.int64)
        return Decision(C, X, np.zeros(0), np.zeros(0, bool), empty, np.zeros(0, bool), empty, empty, np.zeros(len(cat.anime_id)))
    picks = [e for e in led.natural if e.t < t]
    nh = len(picks)
    hist_rows = np.array([e.row for e in picks], dtype=np.int64)
    lengths, ages = led.pick_length[:nh], led.pick_age[:nh]
    hours_c = s.hours[C]
    len_c, age_c = length_bucket(hours_c), age_bucket(s.start[C], t)
    finale_c = finale_bucket(s.finale[C], t)

    # Taste: the user's anime-level mean scores as own percentiles, a dropped media held to
    # their tenth percentile.
    scores = led.rating[before]
    if len(scores):
        scores[dropped] = np.minimum(scores[dropped], np.percentile(scores, 10))
    RA, rated_at = np.unique(cat.media_row[rated], return_inverse=True)
    pct = np.zeros(0)
    if len(RA):
        mean_score = np.bincount(rated_at, weights=scores) / np.bincount(rated_at)
        pct = (_rank(mean_score) - 0.5) / len(RA)
    own_pct = np.full(len(cat.anime_id), 0.5)
    own_pct[RA] = pct

    # Every rated anime against every candidate. A natural pick is always rated before `t`,
    # so the recent picks are rows of the same block.
    D = distances(cat.features[RA], cat.uncertainty[RA], cat.features[C], cat.uncertainty[C])
    D[RA[:, None] == C[None, :]] = math.inf
    latest = hist_rows[::-1][:RECENT]

    # The recent picks, nearest first; continuing a pick is the closest thing to it.
    DH = D[np.searchsorted(RA, latest)]
    DH[latest[:, None] == C[None, :]] = -1
    recent = [_simrank(d) for d in DH]
    for k in range(min(LAGS, nh)):
        X[:, COLUMN[f"F1_sim_lag{k + 1}"]] = recent[k]
    if recent:
        w = 0.5 ** (np.arange(len(recent)) / RECENT_HALF_LIFE)
        X[:, COLUMN["F1_sim_decay10"]] = np.average(recent, axis=0, weights=w)
    nearest_recent = latest[DH.argmin(axis=0)] if nh else np.full(n, -1, dtype=np.int64)

    G, S = cat.genres[C], cat.studios[C]
    G_size = G.sum(axis=1)
    for k in range(min(LAGS, nh)):
        p = hist_rows[-1 - k]
        inter = G[:, cat.genres[p]].sum(axis=1)
        lag = k + 1
        X[:, COLUMN[f"F2_sector_lag{lag}"]] = cat.sector[C] == cat.sector[p]
        X[:, COLUMN[f"F2_region_lag{lag}"]] = cat.region[C] == cat.region[p]
        X[:, COLUMN[f"F2_genreJac_lag{lag}"]] = inter / np.maximum(G_size + cat.genres[p].sum() - inter, 1)
        X[:, COLUMN[f"F2_studio_lag{lag}"]] = S[:, cat.studios[p]].any(axis=1)
        X[:, COLUMN[f"F2_len_lag{lag}"]] = len_c == lengths[-1 - k]
        X[:, COLUMN[f"F2_age_lag{lag}"]] = age_c == ages[-1 - k]

    times = np.array([e.t for e in picks])
    if harness and nh:
        genre_ids = [np.flatnonzero(cat.genres[r]).tolist() for r in hist_rows]
        for facet, pick_values, cand_values in (
            ("sector", cat.sector[hist_rows], cat.sector[C]),
            ("region", cat.region[hist_rows], cat.region[C]),
            ("len", lengths, len_c),
            ("age", ages, age_c),
        ):
            ev, days, never = _due([[int(v)] for v in pick_values], times, t, [[int(v)] for v in cand_values])
            X[:, COLUMN[f"F3_due_{facet}_ev"]] = ev
            X[:, COLUMN[f"F3_due_{facet}_days"]] = days
            X[:, COLUMN[f"F3_never_{facet}"]] = never
        ev, days, never = _due(genre_ids, times, t, [np.flatnonzero(g).tolist() for g in G])
        X[:, COLUMN["F3_due_genre_ev"]], X[:, COLUMN["F3_due_genre_days"]] = ev, days
        X[:, COLUMN["F3_never_genre"]] = never
        last, prior = slice(max(nh - TREND_RECENT, 0), nh), slice(max(nh - TREND_RECENT - TREND_BEFORE, 0), max(nh - TREND_RECENT, 0))
        if prior.stop > prior.start:
            def share(values: np.ndarray, current: np.ndarray, window: slice) -> np.ndarray:
                return (current[:, None] == values[window][None, :]).mean(axis=1)

            X[:, COLUMN["F4_trend_sector"]] = share(cat.sector[hist_rows], cat.sector[C], last) - share(cat.sector[hist_rows], cat.sector[C], prior)
            X[:, COLUMN["F4_trend_len"]] = share(lengths, len_c, last) - share(lengths, len_c, prior)
            frac = cat.genres[hist_rows[last]].mean(axis=0) - cat.genres[hist_rows[prior]].mean(axis=0)
            X[:, COLUMN["F4_trend_genre"]] = (G * frac).sum(axis=1) / np.maximum(G_size, 1)

    nearest_favourite = np.full(n, -1, dtype=np.int64)
    X[:, COLUMN["F5_knn_pct"]] = 0.5
    if len(RA):
        k = min(KNN, len(RA))
        X[:, COLUMN["F5_knn_pct"]] = pct[np.argpartition(D, k - 1, axis=0)[:k]].mean(axis=0)
        favourites = np.flatnonzero(pct >= FAVOURITE)
        if len(favourites):
            DF = D[favourites]
            X[:, COLUMN["F5_top20_sim"]] = _simrank(DF.min(axis=0))
            nearest_favourite = RA[favourites[DF.argmin(axis=0)]]
    X[:, COLUMN["F5_mal"]] = cat.mal[C]
    X[:, COLUMN["F5_mal_missing"]] = cat.mal_missing[C]
    X[:, COLUMN["F5_logvotes"]] = cat.votes[C]

    X[:, COLUMN["F6_loglen"]] = np.log1p(hours_c)
    X[:, COLUMN["F6_long"]] = hours_c >= LONG_HOURS
    if harness and nh:
        hp = np.array([e.hours for e in picks])
        load7 = hp[times >= t - 7 * DAY].sum()
        days_p = np.floor(times / DAY).astype(np.int64)
        roll = [hp[(days_p >= d - 6) & (days_p <= d)].sum() for d in range(days_p[0], _day(t))]
        med = float(np.median(roll)) if roll else load7
        long_t = times[hp >= LONG_HOURS]
        m_load = (math.log((load7 + 1) / (med + 1)) - LOAD_MEAN) / LOAD_SD
        m_long = (math.log1p((t - (long_t[-1] if len(long_t) else times[0])) / DAY) - LONG_MEAN) / LONG_SD
        X[:, COLUMN["F6_loglen_x_load"]] = _z(X[:, COLUMN["F6_loglen"]]) * m_load
        X[:, COLUMN["F6_long_x_days"]] = _z(X[:, COLUMN["F6_long"]]) * m_long

    cont = s.continuation[C]
    X[:, COLUMN["F7_is_cont"]] = cont
    X[:, COLUMN["F7_own_pct"]] = cont * (own_pct[C] - 0.5)
    last_seen = np.full(len(cat.anime_id), -math.inf)
    np.maximum.at(last_seen, cat.media_row[rated], led.t[before])
    X[:, COLUMN["F7_log_days_since"]] = np.where(cont, np.log1p(np.maximum((t - last_seen[C]) / DAY, 0)), 0.0)

    X[:, COLUMN["F8_age_propensity"]] = _propensity(ages, age_c, 7)
    X[:, COLUMN["F9_len_propensity"]] = _propensity(lengths, len_c, len(LENGTH_EDGES) + 1)
    X[:, COLUMN["F10_finale_propensity"]] = _propensity(led.pick_finale[:nh], finale_c, len(FINALE_EDGES) + 2)

    pr = priority[C]
    on_list = pr > 0
    for level in (1, 2, 3):
        X[:, COLUMN[f"W_p{level}"]] = pr == level
    X[:, COLUMN["W_log_age"]] = np.where(on_list, np.log1p(np.maximum(t - touched[C], 0) / DAY), 0.0)
    pace = max(sum(1 for e in picks if e.t >= t - 30 * DAY), 1)
    X[:, COLUMN["W_backlog"]] = np.where(on_list, math.log(max(int((priority > 0).sum()) / pace, 1e-9)), 0.0)

    raw_knn = X[:, COLUMN["F5_knn_pct"]].copy()
    scaled = X[:, SCALED]
    mean, sd = scaled.mean(axis=0), scaled.std(axis=0)
    X[:, SCALED] = np.where(sd > 0, (scaled - mean) / np.where(sd > 0, sd, 1), 0.0)

    size = np.bincount(cat.region)
    coverage = (np.bincount(cat.region[RA], minlength=len(size)) / np.maximum(size, 1))[cat.region]
    return Decision(C, X, raw_knn, on_list, pr, cont, nearest_recent, nearest_favourite, coverage)


def _z(x: np.ndarray) -> np.ndarray:
    if not len(x):
        return x
    sd = x.std()
    return (x - x.mean()) / sd if sd > 0 else np.zeros(len(x))


def weight_vector(weights: dict[str, float]) -> np.ndarray:
    return np.array([weights.get(name, 0.0) for name in NAMES])


# --- The row --------------------------------------------------------------------------------------------

def caps(led: Ledger) -> tuple[int, int]:
    """How many listed anime and continuations each window of the row holds at most:
    docs/features/recommender.md, "The row"."""
    known = ~np.isnan(led.pick_listed)
    p_listed = (led.pick_listed[known].sum() + CAP_PRIOR * POOLED_LISTED) / (known.sum() + CAP_PRIOR)
    n = len(led.pick_cont)
    p_cont = (led.pick_cont.sum() + CAP_PRIOR * POOLED_CONTINUATION) / (n + CAP_PRIOR)
    return round(ROW * p_listed), round(ROW * p_cont)


def _reasons(dec: Decision, w: np.ndarray) -> list[str]:
    kinds = list(_REASON_COLUMNS)
    contribution = np.stack([dec.X[:, _REASON_COLUMNS[k]] @ w[_REASON_COLUMNS[k]] for k in kinds], axis=1)
    best = contribution.argmax(axis=1)
    return [kinds[b] if contribution[i, b] > 0 else "popular" for i, b in enumerate(best)]


def slate(score: np.ndarray, dec: Decision, cat: Catalogue, listed_cap: int, cont_cap: int) -> tuple[np.ndarray, np.ndarray]:
    """The stored order: the model's order, walked in windows of `ROW` with at most
    `listed_cap` listed anime, `cont_cap` continuations and `REGION_CAP` per region each,
    and the explore slots filled from the user's least-covered regions. Returns the
    candidates' positions in rank order and which of them took an explore slot."""
    n = len(score)
    order = np.argsort(-score, kind="stable").tolist()
    regions = cat.region[dec.rows].tolist()
    is_listed, is_cont = dec.listed.tolist(), dec.continuation.tolist()
    low = dec.coverage[dec.rows] <= np.quantile(np.unique(dec.coverage), EXPLORE_COVERAGE)
    pool = np.flatnonzero(~dec.listed & ~dec.continuation & low)
    enjoyment = _z(dec.raw_knn[pool]) + _z(cat.mal[dec.rows[pool]]) + _z(dec.X[pool, COLUMN["F9_len_propensity"]])
    explore_order = pool[np.argsort(-enjoyment, kind="stable")].tolist()
    placed = [False] * n
    explored = np.zeros(n, dtype=bool)
    out: list[int] = []
    # Each window is one pass over the order, so a capped anime is skipped once per window
    # rather than once per tile.
    while len(out) < n:
        size = min(ROW, n - len(out))
        per_region: dict[int, int] = defaultdict(int)
        slots: dict[int, int] = {}
        for slot in (s for s in EXPLORE_SLOTS if s <= size):
            pick = next((i for i in explore_order if not placed[i] and per_region[regions[i]] < REGION_CAP), None)
            if pick is not None:
                placed[pick] = explored[pick] = True
                per_region[regions[pick]] += 1
                slots[slot] = pick
        need = size - len(slots)
        main: list[int] = []
        listed_n = cont_n = 0
        for i in order:
            if len(main) == need:
                break
            if placed[i] or per_region[regions[i]] >= REGION_CAP:
                continue
            if (is_listed[i] and listed_n >= listed_cap) or (is_cont[i] and cont_n >= cont_cap):
                continue
            placed[i] = True
            main.append(i)
            per_region[regions[i]] += 1
            listed_n += is_listed[i]
            cont_n += is_cont[i]
        for i in order:  # caps too tight for what is left: fill in plain order
            if len(main) == need:
                break
            if not placed[i]:
                placed[i] = True
                main.append(i)
        window = iter(main)
        out.extend(slots[slot] if slot in slots else next(window) for slot in range(1, size + 1))
        order = [i for i in order if not placed[i]]
        explore_order = [i for i in explore_order if not placed[i]]
    ranked = np.array(out, dtype=np.int64)
    return ranked, explored[ranked]


def ranking_score(dec: Decision, w: np.ndarray) -> np.ndarray:
    """The logit plus the enjoyment tilt."""
    return dec.X @ w + ALPHA * dec.X[:, COLUMN["F5_knn_pct"]]


def recommend(
    cat: Catalogue, led: Ledger, now: float, weights: dict[str, float] | None = None, *, hot: bool = True,
) -> list[Pick]:
    """The user's whole ranking at `now`: every candidate, in the row's order, with the
    reason it is there."""
    dec = decide(cat, led, now, hot=hot)
    if not len(dec.rows):
        return []
    w = weight_vector(WEIGHTS if weights is None else weights)
    score = ranking_score(dec, w)
    reasons = _reasons(dec, w)
    order, explored = slate(score, dec, cat, *caps(led))
    picks = []
    for rank, (i, explore) in enumerate(zip(order.tolist(), explored.tolist(), strict=True), start=1):
        kind = "explore" if explore else "continue" if dec.continuation[i] else reasons[i]
        ref = None
        if kind == "recent" and dec.nearest_recent[i] >= 0:
            ref = int(cat.anime_id[dec.nearest_recent[i]])
        elif kind == "favourite" and dec.nearest_favourite[i] >= 0:
            ref = int(cat.anime_id[dec.nearest_favourite[i]])
        detail = f"P{dec.priority[i]}" if kind == "watchlist" else None
        picks.append(Pick(int(cat.anime_id[dec.rows[i]]), rank, kind, ref, detail))
    return picks
