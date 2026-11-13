"""`recommender_compute` on small synthetic catalogues: the natural-history rule, who is a
candidate and what picking it commits to, the readiness verdict, the features that carry a
stated rule, and the row's caps. The prod numbers behind the constants are a study, not a
test."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.models.media import (
    AIRING_STATUS_CURRENTLY_AIRING,
    AIRING_STATUS_FINISHED_AIRING,
    AIRING_STATUS_NOT_YET_AIRED,
    MAIN_STORY_RELATIONS,
    SEASON_ORDER,
)
from app.schemas.media_filter_schema import RatedState
from app.services import recommender_compute as rc
from app.services.filter_service import chronological_media_key
from app.services.rating_service import _rated_state

T0 = datetime(2026, 10, 1, tzinfo=UTC).timestamp()
DAY = rc.DAY
NO_RATINGS = (np.zeros(0, dtype=np.int64), np.zeros(0, dtype="U9"))


def _key(season, year):
    """`search_filters.SEASON_KEY` for one season."""
    return year * 10 + SEASON_ORDER[season] if season and year else None


def _media(media_id, anime_id, *, main=True, episodes=12, duration=1440, year=2024, season="Winter",
           unaired=False, airing=False, aired_from=None, aired_to=None):
    return rc.MediaRow(
        media_id=media_id, anime_id=anime_id, mal_id=media_id, main=main, media_type="TV",
        episodes=episodes, duration_seconds=duration,
        total_watch_time=episodes * duration if episodes and duration else None,
        season_year=year, season_name=season, season_key=_key(season, year),
        aired_from=aired_from, aired_to=aired_to, unaired=unaired, airing=airing,
    )


def _star(anime_id, features, *, uncertainty=0.0, sector=1, region=None, votes=1000.0):
    return rc.StarRow(anime_id, list(features), uncertainty, sector, anime_id if region is None else region,
                      score=7.0, votes=votes, genres=(), studios=())


def _catalogue(stars, media):
    return rc.catalogue(stars, media, chronological_media_key)


def _rating(media_id, at, status="completed", rating=7.0):
    return rc.RatingRow(media_id, rating, status, at, at if status == "completed" else None, None)


def _ledger(cat, ratings, listings=(), franchise=None):
    """The whole watchlist history known."""
    return rc.ledger(cat, list(ratings), list(listings), franchise=franchise, listed_from=0.0)


# --- The natural history -------------------------------------------------------------------------

@pytest.mark.parametrize(("days", "start", "kept", "dropped"), [
    # One-day import of 238 anime, then a natural pick.
    ({0: (2107.0, 238), 3: (5.0, 1)}, 1, {3}, {0}),
    # A three-day import.
    ({0: (1333.0, 100), 1: (593.0, 64), 2: (760.0, 134), 3: (5.0, 1)}, 3, {3}, {0, 1, 2}),
    # Imports on two weekends with light weekdays between: one import.
    ({0: (400.0, 60), 1: (300.0, 40), 3: (5.0, 1), 4: (4.0, 1), 7: (500.0, 70), 9: (5.0, 1)}, 8, {9}, {3, 4}),
    # Fourteen days away, then six anime (30 h) in one evening: natural.
    ({0: (2000.0, 200), 2: (5.0, 1), 16: (30.0, 6)}, 1, {2, 16}, set()),
    # Four short shows (18 h) the day after a rating: too few anime to be an import.
    ({0: (2000.0, 200), 2: (5.0, 1), 3: (18.0, 4)}, 1, {2, 3}, set()),
    # Thirty old anime four months in: left out, the start unchanged.
    ({0: (2000.0, 200), 2: (5.0, 1), 120: (5.0, 1), 123: (150.0, 30)}, 1, {2, 120}, {123}),
    # Three natural weeks, then a big import: no import phase, that day left out.
    ({0: (5.0, 1), 7: (5.0, 1), 21: (2000.0, 200), 22: (5.0, 1)}, 0, {0, 7, 22}, {21}),
])
def test_natural_days_follow_the_import_rule(days, start, kept, dropped):
    natural, first = rc.natural_days(days, None)
    assert first == start
    assert kept <= natural
    assert not (dropped & natural)


def test_an_override_replaces_the_detected_start():
    natural, first = rc.natural_days({0: (2000.0, 200), 2: (5.0, 1), 9: (5.0, 1)}, 5)
    assert first == 5
    assert natural == {9}


def test_the_override_date_feeds_the_ledger():
    cat = _franchise_catalogue()
    led = rc.ledger(cat, [_rating(10, T0), _rating(20, T0 + 60)], [], override=date(2026, 9, 1))
    assert led.start == (date(2026, 9, 1) - rc.EPOCH).days


def test_a_pick_is_listed_when_its_anime_was_on_the_list_at_the_time():
    """By anime, not media: a pick of season one counts as listed when only season two was.
    Before `listed_from` nothing is known."""
    cat = _franchise_catalogue()
    listings = [rc.ListingRow(10, 1, T0 - DAY, None), rc.ListingRow(21, 2, T0 - DAY, None)]
    ratings = [_rating(10, T0), _rating(20, T0 + 2 * DAY), _rating(40, T0 + 4 * DAY)]
    led = rc.ledger(cat, ratings, listings, listed_from=T0 + DAY)
    assert np.isnan(led.pick_listed[0])
    assert led.pick_listed[1:].tolist() == [1.0, 0.0]


def test_a_completed_media_counts_when_it_was_finished():
    """An on_hold → completed edit is stamped by its first watch event, not the rating."""
    paused_then_done = rc.RatingRow(1, 7.0, "completed", T0, T0 + 3 * DAY, None)
    assert rc.event_time(paused_then_done) == T0 + 3 * DAY
    assert rc.event_time(rc.RatingRow(1, 7.0, "on_hold", T0, None, None)) == T0


# --- Candidates and commitment ------------------------------------------------------------------------

def _franchise_catalogue():
    stars = [_star(a, [float(a), 0.0]) for a in (1, 2, 3, 4, 5)]
    media = [
        _media(10, 1),                                              # 1: untouched
        _media(20, 2), _media(21, 2, year=2025), _media(22, 2, main=False),  # 2: S1, S2, a side story
        _media(30, 3), _media(31, 3, year=2025),                    # 3: S1 dropped
        _media(40, 4),                                              # 4: everything watched
        _media(50, 5, unaired=True),                                # 5: nothing aired
    ]
    return _catalogue(stars, media)


def _rated(cat, *pairs):
    """Positions and statuses of the media rated (media id, status)."""
    positions = np.array([cat.position_of[m] for m, _ in pairs], dtype=np.int64)
    return positions, np.array([s for _, s in pairs], dtype="U9")


def test_candidates_are_the_rated_states_with_story_left():
    cat = _franchise_catalogue()
    s = rc.state(cat, T0, *_rated(cat, (20, "completed"), (30, "dropped"), (40, "completed")))
    by_anime = dict(zip(cat.anime_id.tolist(), s.candidate.tolist(), strict=True))
    assert by_anime == {1: True, 2: True, 3: False, 4: False, 5: False}
    assert s.continuation[cat.row_of[2]] and not s.continuation[cat.row_of[1]]


@pytest.mark.parametrize("statuses", [
    {}, {20: "completed"}, {20: "on_hold"}, {20: "dropped"}, {20: "completed", 21: "completed"},
    {21: "completed"}, {20: "completed", 21: "on_hold"}, {20: "completed", 22: "dropped"},
])
def test_the_candidate_rule_agrees_with_the_rated_state(statuses):
    """An unlisted anime is a candidate exactly when its rated state is none, in_progress
    or on_hold — the app's rule, reached through the media rather than the counts. A
    dropped side story drops nothing."""
    cat = _franchise_catalogue()
    s = rc.state(cat, T0, *_rated(cat, *statuses.items()))
    main = {m: v for m, v in statuses.items() if m != 22}
    done = sum(v == "completed" for v in main.values())
    counts = SimpleNamespace(
        n_all=3, done_all=done + (statuses.get(22) == "completed"), n_main=2, done_main=done,
        dropped_main=sum(v == "dropped" for v in main.values()),
        on_hold_main=sum(v == "on_hold" for v in main.values()),
    )
    expected = not statuses or _rated_state(counts) in {RatedState.IN_PROGRESS, RatedState.ON_HOLD}
    assert bool(s.candidate[cat.row_of[2]]) is expected


def test_a_listed_rewatch_is_a_candidate_and_counts_its_hours():
    cat = _franchise_catalogue()
    s = rc.state(cat, T0, *_rated(cat, (40, "completed")), np.array([cat.position_of[40]], dtype=np.int64))
    assert s.candidate[cat.row_of[4]]
    assert s.hours[cat.row_of[4]] == pytest.approx(12 * 1440 / 3600)


def test_the_commitment_sums_what_is_listed_not_the_whole_story():
    """Listing S1 again beside S2 makes the commitment both; unlisted, it is S2 alone."""
    cat = _franchise_catalogue()
    rated = _rated(cat, (20, "completed"))
    season = 12 * 1440 / 3600
    assert rc.state(cat, T0, *rated).hours[cat.row_of[2]] == pytest.approx(season)
    both = np.array([cat.position_of[20], cat.position_of[21]], dtype=np.int64)
    assert rc.state(cat, T0, *rated, both).hours[cat.row_of[2]] == pytest.approx(2 * season)


def test_a_standalone_media_is_a_commitment_of_its_own():
    """A 20 h+ media stands alone when it comes first, and ends the sum when it comes later."""
    long = {"episodes": 60, "duration": 1440}
    media = [
        _media(10, 1, year=2020, **long), _media(11, 1, year=2021),
        _media(20, 2, year=2020), _media(21, 2, year=2021), _media(22, 2, year=2022, **long),
    ]
    cat = _catalogue([_star(1, [0.0]), _star(2, [1.0])], media)
    hours = rc.state(cat, T0, *NO_RATINGS).hours
    assert hours[cat.row_of[1]] == pytest.approx(60 * 1440 / 3600)
    assert hours[cat.row_of[2]] == pytest.approx(2 * 12 * 1440 / 3600)


# --- Readiness ----------------------------------------------------------------------------------------

def test_the_hot_setting_leaves_out_hot_anime_and_waiting_ones_never_show():
    """Off, anything the watchlist would call Hot is no candidate: an airing season even in
    its finale week, or, read off the whole main story of an unlisted anime, a season due
    next season. A listed rewatch whose sequel has not landed is Waiting, and never shown."""
    media = [
        _media(10, 1, airing=True, aired_from=date(2026, 7, 13)),
        _media(20, 2), _media(21, 2, unaired=True, year=2026, season="Fall"),
        _media(30, 3, aired_to=date(2026, 3, 20)),
        _media(40, 4), _media(41, 4, unaired=True, year=2028, season="Winter"),
    ]
    cat = _catalogue([_star(a, [float(a)]) for a in (1, 2, 3, 4)], media)
    rewatch = [rc.ListingRow(40, 1, T0 - DAY, None), rc.ListingRow(41, 1, T0 - DAY, None)]
    led = _ledger(cat, [_rating(40, T0 - 30 * DAY)], rewatch)
    assert {p.anime_id for p in rc.recommend(cat, led, T0, hot=False)} == {3}
    assert {p.anime_id for p in rc.recommend(cat, led, T0)} == {1, 2, 3}


def test_a_listed_unaired_sequel_leaves_the_aired_season_a_candidate():
    """With only an unannounced sequel listed, the list commits to nothing yet, so the verdict
    reads the main story like an unlisted anime's: the aired season left is ready, not
    Waiting on the sequel."""
    media = [_media(10, 1, year=2020), _media(11, 1, year=2021), _media(12, 1, unaired=True, year=None, season=None)]
    cat = _catalogue([_star(1, [0.0])], media)
    led = _ledger(cat, [_rating(10, T0 - 30 * DAY)], [rc.ListingRow(12, 1, T0 - DAY, None)])
    assert [p.anime_id for p in rc.recommend(cat, led, T0)] == [1]


def test_the_franchise_signals_reach_the_verdict():
    """A listed season is Hot when the franchise has an unlisted season airing — the signal
    the watchlist's own query computes, dropped seasons already excused."""
    cat = _catalogue([_star(1, [0.0])], [_media(10, 1), _media(11, 1, year=2026, airing=True)])
    listing = [rc.ListingRow(10, 1, T0 - DAY, None)]
    airing = _ledger(cat, [], listing, franchise={1: (True, None)})
    quiet = _ledger(cat, [], listing, franchise={1: (False, None)})
    assert rc.recommend(cat, airing, T0, hot=False) == []
    assert [p.anime_id for p in rc.recommend(cat, quiet, T0, hot=False)] == [1]


_CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "frontend" / "src" / "tests" / "fixtures" / "readiness-cases.json").read_text()
)
_NOW = datetime.fromisoformat(_CASES["now"]).timestamp()
_PHASE = {
    AIRING_STATUS_FINISHED_AIRING: "aired", AIRING_STATUS_CURRENTLY_AIRING: "airing",
    AIRING_STATUS_NOT_YET_AIRED: "unaired",
}


@pytest.mark.parametrize("case", _CASES["cases"], ids=[c["label"] for c in _CASES["cases"]])
def test_the_verdict_matches_the_watchlists(case):
    """The watchlist's own case table, walked by the backend's rule."""
    items = []
    for raw in case["items"]:
        o = {**_CASES["defaults"], **raw}
        items.append(rc.ReadyItem(
            main=o["relation_type"] in MAIN_STORY_RELATIONS, phase=_PHASE[o["airing_status"]],
            season_key=_key(*o["season"]) if o["season"] else None,
            watch_status=o["watch_status"], total_watch_time=o["total_watch_time"],
        ))
    upcoming = _key(*case["franchise_upcoming"]) if case.get("franchise_upcoming") else None
    verdict = rc.readiness(items, case.get("franchise_airing", False), upcoming, rc.next_season_key(_NOW))
    assert verdict == case["expected"]


def test_next_season_rolls_fall_into_winter():
    assert rc.next_season_key(datetime(2026, 11, 15, tzinfo=UTC).timestamp()) == _key("Winter", 2027)


@pytest.mark.parametrize(("media", "bucket"), [
    # Airing, the finale weeks ahead: its own bucket, apart from what just finished.
    ({"airing": True, "aired_from": date(2026, 9, 20), "episodes": 12}, 0),
    # Airing with no end date and no episode count: still airing.
    ({"airing": True, "aired_from": date(2026, 9, 20), "episodes": None}, 0),
    # Its finale airs in three days: finale week counts with the month after.
    ({"airing": True, "aired_from": date(2026, 7, 13), "episodes": 12}, 1),
    # Finished ten days ago.
    ({"aired_to": date(2026, 9, 21)}, 1),
    # Finished two months ago.
    ({"aired_to": date(2026, 8, 1)}, 2),
    # No dates at all.
    ({}, 6),
])
def test_freshness_runs_from_the_finale_not_the_start(media, bucket):
    cat = _catalogue([_star(1, [0.0])], [_media(10, 1, **media)])
    assert rc.finale_bucket(rc.state(cat, T0, *NO_RATINGS).finale, T0)[0] == bucket


# --- Features ------------------------------------------------------------------------------------------

def test_continuing_the_last_pick_is_the_nearest_thing_to_it():
    """The galaxy distance puts a star's own row at infinity; the lag features count a
    continuation of the pick as the closest candidate instead."""
    media = [_media(10, 1), _media(11, 1, year=2025)] + [_media(10 * a, a) for a in range(2, 7)]
    cat = _catalogue([_star(a, [float(a)]) for a in range(1, 7)], media)
    dec = rc.decide(cat, _ledger(cat, [_rating(10, T0)]), T0 + DAY)
    assert cat.anime_id[dec.rows[dec.X[:, rc.COLUMN["F1_sim_lag1"]].argmax()]] == 1


def test_similarity_carries_each_stars_uncertainty():
    """Two candidates equally far from the pick in features: the one the catalogue says
    less about sits farther. Fails if a plain distance replaces the galaxy's."""
    stars = [_star(1, [0.0, 0.0]), _star(2, [1.0, 0.0]), _star(3, [0.0, 1.0], uncertainty=5.0), _star(4, [9.0, 9.0])]
    cat = _catalogue(stars, [_media(10 * a, a) for a in range(1, 5)])
    dec = rc.decide(cat, _ledger(cat, [_rating(10, T0)]), T0 + DAY)
    sim = dict(zip(cat.anime_id[dec.rows].tolist(), dec.X[:, rc.COLUMN["F1_sim_lag1"]].tolist(), strict=True))
    assert sim[2] > sim[3]


def test_the_watchlist_features_stay_unstandardised():
    """A listed anime's priority reads 1, not the z of a handful among thousands."""
    cat = _wide_catalogue()
    led = _ledger(cat, [], [rc.ListingRow(1, 1, T0 - DAY, None)])
    dec = rc.decide(cat, led, T0)
    assert sorted(set(dec.X[:, rc.COLUMN["W_p1"]].tolist())) == [0.0, 1.0]


def test_the_list_is_unknown_before_listed_from():
    """Replayed before the watchlist's history starts, today's list reads as empty: no listed
    anime, no watchlist feature."""
    cat = _wide_catalogue()
    listing = [rc.ListingRow(1, 1, T0 - 10 * DAY, None)]
    led = rc.ledger(cat, [], listing, listed_from=T0)
    assert not rc.decide(cat, led, T0 - DAY).listed.any()
    assert rc.decide(cat, led, T0).listed.any()


# --- The row ---------------------------------------------------------------------------------------------

def test_caps_follow_the_users_own_mix_pulled_toward_the_pool():
    led = _ledger(_franchise_catalogue(), [])
    assert rc.caps(led) == (round(rc.ROW * rc.POOLED_LISTED), round(rc.ROW * rc.POOLED_CONTINUATION))
    listed_cap, cont_cap = rc.caps(led._replace(pick_listed=np.zeros(80), pick_cont=np.ones(80, dtype=bool)))
    assert listed_cap < round(rc.ROW * rc.POOLED_LISTED) and cont_cap > round(rc.ROW * rc.POOLED_CONTINUATION)


def _wide_catalogue(n=120, regions=30):
    stars = [_star(a, [float(a % 7), float(a % 5)], sector=a % 3, region=a % regions, votes=10.0 * a)
             for a in range(1, n + 1)]
    return _catalogue(stars, [_media(a, a) for a in range(1, n + 1)])


def test_the_row_holds_its_caps_and_slots_and_ranks_everyone_once():
    cat = _wide_catalogue()
    dec = rc.decide(cat, _ledger(cat, []), T0)
    n = len(dec.rows)
    listed = np.zeros(n, dtype=bool)
    listed[:40] = True
    dec = dec._replace(listed=listed, coverage=np.where(cat.region == 0, 0.0, 0.5))
    score = np.where(listed, 10.0, 0.0) + np.linspace(1, 0, n)  # the listed would fill the row
    order, explored = rc.slate(score, dec, cat, listed_cap=5, cont_cap=5)
    assert sorted(order.tolist()) == list(range(n))
    first = order[: rc.ROW]
    assert listed[first].sum() == 5
    assert [i + 1 for i in np.flatnonzero(explored[: rc.ROW])] == list(rc.EXPLORE_SLOTS)
    assert set(cat.region[dec.rows[order[explored]]]) == {0}


def test_a_region_holds_at_most_three_tiles_per_window():
    """The four best-scored anime share one region: the window takes three of them and the
    fourth waits for the next one."""
    cat = _wide_catalogue()
    dec = rc.decide(cat, _ledger(cat, []), T0)
    dec = dec._replace(coverage=np.where(cat.region == 0, 0.0, 0.5))
    crowded = cat.region[dec.rows] == 1
    score = np.where(crowded, 10.0, 0.0) + np.linspace(1, 0, len(dec.rows))
    order, _ = rc.slate(score, dec, cat, listed_cap=rc.ROW, cont_cap=rc.ROW)
    assert crowded.sum() == 4
    assert crowded[order[: rc.ROW]].sum() == rc.REGION_CAP
    assert crowded[order[rc.ROW : 2 * rc.ROW]].sum() == 1


def test_a_new_user_gets_the_catalogue_s_popular_picks():
    cat = _wide_catalogue(regions=1)
    picks = rc.recommend(cat, _ledger(cat, []), T0)
    assert len(picks) == len(cat.anime_id)
    plain = [p for p in picks[: rc.ROW] if p.kind != "explore"]
    assert {p.kind for p in plain} == {"popular"}
    votes = [cat.votes[cat.row_of[p.anime_id]] for p in plain]
    assert votes == sorted(votes, reverse=True)
