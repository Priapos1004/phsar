"""`recommender_eval` and the backtest's backup diff on synthetic data: the fit recovers what
drew the picks, the splits keep each test decision out of its own training, and the watchlist
metrics' arithmetic. What the harness measures on the prod data is a study, not a test."""

import json
import math

import numpy as np
import pytest

from app.services import recommender_compute as rc
from app.services import recommender_eval as ev
from scripts.backtest_recommender import listings_from
from tests.services.test_recommender_compute import (
    DAY,
    T0,
    _catalogue,
    _media,
    _rating,
    _star,
)

LIVE = np.zeros(len(rc.NAMES), dtype=bool)
LIVE[:3] = True


def _case(X, target=0, user=1, t=0.0):
    n = len(X)
    empty = np.zeros(n, dtype=np.int64)
    dec = rc.Decision(
        np.arange(n), X, np.zeros(n), np.zeros(n, bool), empty, np.zeros(n, bool), empty, empty, np.zeros(n), empty,
        np.zeros(n), np.zeros(n, bool),
    )
    return ev.Case(user, t, dec, target, True, (rc.ROW, rc.ROW))


def _drawn(w_true, n=400, k=30, seed=0):
    """Decisions whose pick is drawn from the conditional logit with `w_true`."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        X = np.zeros((k, len(rc.NAMES)))
        X[:, :3] = rng.standard_normal((k, 3))
        p = np.exp(X @ w_true)
        out.append(_case(X, int(rng.choice(k, p=p / p.sum()))))
    return out


def test_the_fit_recovers_the_weights_that_drew_the_picks():
    w_true = np.zeros(len(rc.NAMES))
    w_true[:3] = [1.0, -0.5, 0.0]
    w = ev.fit(_drawn(w_true), LIVE, lam=0.1)
    assert w[:3] == pytest.approx([1.0, -0.5, 0.0], abs=0.2)
    assert not w[~LIVE].any()


def test_a_per_user_fit_shrinks_toward_its_prior_not_zero():
    prior = np.zeros(len(rc.NAMES))
    prior[:3] = [0.7, 0.3, -0.2]
    assert ev.fit([], LIVE, prior=prior) == pytest.approx(prior)
    assert ev.fit(_drawn(np.zeros(len(rc.NAMES)), n=40), LIVE, lam=1e6, prior=prior) == pytest.approx(prior, abs=1e-3)


def test_no_test_decision_is_trained_on():
    """The time split tests each user's latest 40% on a fit to their earlier decisions and
    everyone else's; leave-one-user-out on a fit to the others alone."""
    chosen = [_case(np.zeros((2, len(rc.NAMES))), user=u, t=float(i)) for u, n in ((1, 10), (2, 5)) for i in range(n)]
    s = ev.splits(chosen)
    (train1, test1), (train2, test2) = s["time"]
    assert test1.tolist() == [6, 7, 8, 9] and sorted(train1.tolist()) == [0, 1, 2, 3, 4, 5, 10, 11, 12, 13, 14]
    assert test2.tolist() == [13, 14] and sorted(train2.tolist()) == [*range(10), 10, 11, 12]
    assert [(tr.tolist(), te.tolist()) for tr, te in s["louo"]] == [
        (list(range(10, 15)), list(range(10))), (list(range(10)), list(range(10, 15))),
    ]


def _anime(n=8):
    """`n` one-season anime, each in a region of its own."""
    return _catalogue([_star(a, [float(a), 0.0]) for a in range(1, n + 1)], [_media(a, a) for a in range(1, n + 1)])


def test_the_watchlist_metrics_count_picks_against_the_candidates():
    """Five candidates at the fourth pick, one at P1 and one at P2, both listed 13 days
    earlier on one list; the pick is the P1 one. Random choice would pick P1 a fifth of the
    time, so its lift is 5; P1 was listed 13 noons before converting."""
    cat = _anime()
    listings = [
        rc.ListingRow(5, 1, T0 - 10 * DAY, T0 + 3 * DAY + 1, "A"),
        rc.ListingRow(6, 2, T0 - 10 * DAY, None, "A"),
    ]
    ratings = [_rating(m, T0 + d * DAY) for d, m in enumerate((1, 2, 3, 5))]
    led = rc.ledger(cat, ratings, listings, listed_from=T0 - 10 * DAY)
    chosen = ev.cases(cat, {1: led})
    assert len(chosen) == 1 and len(chosen[0].dec.rows) == 5
    report = ev.watchlist_metrics(cat, {1: led}, chosen, now=T0 + 5 * DAY)["1"]
    assert report["listed_share"] == 0.25
    assert report["lift"]["priority"]["1"] == {"lift": 5.0, "picks": 1}
    assert report["lift"]["priority"]["unlisted"] == {"lift": 0.0, "picks": 0}
    assert report["lift"]["age"]["8-30d"] == {"lift": 2.5, "picks": 1}
    assert report["lift"]["list"]["A"] == {"lift": 2.5, "picks": 1}
    assert report["hazard"]["priority"]["1"] == {"per_100_days": round(100 / 13, 2), "picks": 1, "days": 13}
    assert report["hazard"]["priority"]["2"] == {"per_100_days": 0.0, "picks": 0, "days": 15}


def test_the_backups_rebuild_each_entrys_stretches():
    """A raise between two backups splits the entry; a rating between the last backup holding
    it and the first without ends it right after the pick; an entry gone without a rating
    ends at the first backup without it; one still listed runs on."""
    s1, s2, s3 = T0, T0 + 7 * DAY, T0 + 14 * DAY
    raised, watched = T0 + 3 * DAY, T0 + 10 * DAY
    listed = T0 - DAY
    found = [
        (s1, {(1, 10, listed): (3, "A", listed), (1, 20, listed): (2, "A", listed)}),
        (s2, {(1, 10, listed): (1, "A", raised), (1, 30, s1 + DAY): (2, "B", s1 + DAY)}),
        (s3, {(1, 30, s1 + DAY): (2, "B", s1 + DAY)}),
    ]
    out = listings_from(found, {(1, 10): watched})[1]
    assert sorted(out) == sorted([
        rc.ListingRow(10, 3, listed, raised, "A"), rc.ListingRow(10, 1, raised, watched + 1, "A"),
        rc.ListingRow(20, 2, listed, s2, "A"),
        rc.ListingRow(30, 2, s1 + DAY, None, "B"),
    ])


def test_the_whole_report_runs_on_two_users():
    """The weekly job's summary end to end on a small history, as JSON the job row can hold:
    every family ablated, the fit's weights over the shipped features alone, and the list
    unknown throughout, so it waits."""
    cat = _anime(n=40)
    histories = {u: ([_rating(m, T0 + d * DAY) for d, m in enumerate(range(first, first + 8))], [], {}) for u, first in ((1, 1), (2, 20))}
    summary = json.loads(json.dumps(ev.weekly(cat, histories, math.inf, {}, [], rc.WEIGHTS, [], T0 + 10 * DAY)))
    report = summary["report"]
    assert report["decisions"] == {"total": 10, "1": 5, "2": 5}
    unranked = {f"{rc.family(n)}_unranked" for n in rc.NAMES if n not in rc.WEIGHTS and rc.family(n) not in rc.HARNESS}
    assert set(report["ablations"]) == {*dict.fromkeys(ev._FAMILY), "W_backlog", *unranked}
    assert set(report["weights"]["refit"]) == set(rc.WEIGHTS)
    assert report["refit"]["louo"]["row"]["n"] == 10
    assert len(report["refit"]["louo"]["per_decision"]) == 10
    assert summary["verdict"] == "waiting" and summary["log"]["picks"] == 0


# --- The weekly job -------------------------------------------------------------------------------

def _refit(per_decision: dict[str, float], louo: dict[str, float] | None = None, weights=None):
    """A report as `guards` reads it: the refit's per-decision NLLs and weights."""
    return {
        "refit": {"time": {"per_decision": per_decision}, "louo": {"per_decision": louo or {}}},
        "weights": {"refit": weights or {}},
    }


def test_the_nll_guard_compares_the_decisions_both_runs_tested():
    """Paired over shared decisions: a rise of .1 on both trips, though the unshared decision
    fell; .04 on both stays under the floor, and a mean rise of .2 with a standard error of .4
    within noise."""
    before = {"report": _refit({"1:10": 5.0, "1:20": 5.0, "2:30": 9.0})}
    risen = ev.guards(_refit({"1:10": 5.1, "1:20": 5.1, "1:40": 1.0}), {}, before)
    assert [(g["split"], g["n"], g["tripped"]) for g in risen] == [("time", 2, True)]
    assert risen[0]["change"] == pytest.approx(0.1)
    assert not ev.guards(_refit({"1:10": 5.04, "1:20": 5.04}), {}, before)[0]["tripped"]
    noisy = ev.guards(_refit({"1:10": 5.6, "1:20": 4.8}), {}, before)  # mean +.2, but SE .4
    assert not noisy[0]["tripped"]
    assert ev.guards(_refit({"1:10": 9.0, "1:20": 9.0}), {}, None) == []


def test_a_large_live_weight_changing_sign_trips_the_flip_guard():
    """Only a weight above 0.2 counts, and only a real change of sign: one refit to zero is
    a weight the data no longer supports, not a reversal."""
    live = {"big": 0.5, "small": 0.1, "to_zero": -0.3}
    checks = ev.guards(_refit({}, weights={"big": -0.01, "small": -0.4, "to_zero": 0.0}), live, None)
    assert [(g["name"], g["tripped"]) for g in checks] == [("big", True)]


def _both(nll, p, louo_p=None):
    return {"time": {"hit25": 0.0, "nll": nll, "p": p}, "louo": {"hit25": 0.0, "nll": nll, "p": p if louo_p is None else louo_p}}


def _rewatch(family, own, p):
    return {split: {"n": 5, "family": {"hit10": family}, "own_score": {"hit10": own}, "p": p} for split in ("time", "louo")}


def test_a_left_out_family_would_help_only_after_three_runs_in_a_row():
    """F3 and the rewatch family help beyond noise on both splits in all three runs; a shipped
    family's removal ablation never counts as left out."""
    good = {"ablations": {"F3": _both(0.1, 0.01), "F1": _both(0.2, 0.001)}, "rewatch": _rewatch(0.5, 0.2, 0.01)}
    assert ev.would_help(good, [good, good]) == ["F3", "rewatch"]
    one_split = {"ablations": {"F3": _both(0.1, 0.01, louo_p=0.2)}, "rewatch": _rewatch(0.5, 0.2, 0.2)}
    assert ev.would_help(good, [one_split, good]) == []
    assert ev.would_help(good, [good]) == []


def _rewatch_world():
    """Thirteen anime, each its own region: one season each, but two for 12. The user watches
    1–5 on days 0–4, the first season of 12 on day 3, drops 13 on day 2, watches 6 on day 19,
    then imports 7–11 on day 20; anime 3 is on their list throughout."""
    cat = _catalogue(
        [_star(a, [float(a), 0.0]) for a in range(1, 14)],
        [*(_media(a, a) for a in range(1, 12)), _media(12, 12), _media(13, 12, year=2025), _media(14, 13)],
    )
    days = [(1, 0), (2, 1), (3, 2), (4, 3), (12, 3), (5, 4), (6, 19), *((m, 20) for m in range(7, 12))]
    ratings = [*(_rating(m, T0 + d * DAY) for m, d in days), _rating(14, T0 + 2 * DAY, status="dropped")]
    led = rc.ledger(cat, ratings, [rc.ListingRow(3, 2, T0 - DAY, None)], listed_from=0.0)
    first = [(m, T0 + d * DAY) for m, d in days]
    return cat, led, first


def test_a_complete_rewatch_is_a_decision_among_the_finished_unlisted_anime():
    """Rewatching 1 on day 10 is one, among 1, 2, 4 and 5: 3 is listed, 12 has a season left
    and 13 was dropped. A rewatch straight after first watching the same anime (6), on the import
    day (2), of the listed anime (3) and of the season with one to go (12) are none."""
    cat, led, first = _rewatch_world()
    rewatches = [
        (1, T0 + 10 * DAY), (6, T0 + 19 * DAY + 7200), (2, T0 + 20 * DAY + 60), (3, T0 + 25 * DAY), (12, T0 + 27 * DAY),
    ]
    watches = sorted(first + rewatches, key=lambda w: w[1])
    runs = {1: ev.rewatch_runs(cat, led, watches)}
    chosen = ev.rewatch_cases(cat, {1: led}, runs)
    assert [(c.t, int(cat.anime_id[c.dec.rows[c.target]])) for c in chosen] == [(T0 + 10 * DAY, 1)]
    assert sorted(cat.anime_id[chosen[0].dec.rows].tolist()) == [1, 2, 4, 5]


def test_a_rewatch_on_an_import_day_still_marks_the_anime_rewatched():
    cat, led, first = _rewatch_world()
    watches = sorted([*first, (2, T0 + 20 * DAY + 60), (4, T0 + 30 * DAY)], key=lambda w: w[1])
    (case,) = ev.rewatch_cases(cat, {1: led}, {1: ev.rewatch_runs(cat, led, watches)})
    rewatched = case.dec.X[:, 3]
    is_2 = cat.anime_id[case.dec.rows] == 2
    assert (rewatched[is_2] > 0).all() and (rewatched[~is_2] < 0).all()


def test_the_rewatch_report_ranks_the_plain_own_score_order_too():
    """The baseline orders each rewatch's candidates by own score alone: ranks 1, 12, 3, 15, 2,
    11, 4, 20, 1, 6 put six of ten in the top 10, median 5. Ties take their mean place, so a
    pick tied with all 20 ranks 10.5 under either order."""
    def case(user, t, rank, own=None):
        X = np.zeros((20, len(ev.REWATCH_FEATURES)))
        X[:, 0] = np.linspace(1, 0, 20) if own is None else own
        return ev.Rewatch(user, t, ev.Scored(np.arange(20), X), rank - 1)

    chosen = [case(u, float(i), r) for u, ranks in ((1, (1, 12, 3, 15, 2)), (2, (11, 4, 20, 1, 6))) for i, r in enumerate(ranks)]
    assert ev.rewatch_report(chosen)["louo"]["own_score"] == {"hit10": 0.6, "median_rank": 5.0}
    tied = [case(u, float(i), 1, np.zeros(20)) for u in (1, 2) for i in range(2)]
    out = ev.rewatch_report(tied)["louo"]
    assert out["own_score"] == out["family"] == {"hit10": 0.0, "median_rank": 10.5}


def test_the_row_is_judged_on_the_users_next_picks_not_on_days():
    """One pick a day, anime 1–9. Shown on day 0: 3 is the second pick after, so watched; 9
    is the eighth, past the five that judge it. Shown on day 5: 10 has three picks after it
    and isn't among them, so it waits, however long ago that was."""
    cat = _anime(n=12)
    led = rc.ledger(cat, [_rating(m, T0 + (m - 1) * DAY) for m in range(1, 10)], [])
    exposure = [(1, 3, "fresh", T0 + 0.5 * DAY), (1, 9, "recent", T0 + 0.5 * DAY), (1, 10, "recent", T0 + 5.5 * DAY)]
    out = ev.online(cat, {1: led}, {}, exposure)
    assert out["by_reason"] == {
        "fresh": {"judged": 1, "watched": 1, "share": 1.0}, "recent": {"judged": 1, "watched": 0, "share": 0.0},
    }
    assert out["waiting"] == 1


@pytest.fixture
def stub_report(monkeypatch):
    """`evaluate` reduced to what `weekly` reads: 30 logged decisions, 16 and 14 per user."""
    def evaluate(cat, ledgers, weights, *, refit, now):
        return {
            "refit": {"time": {"per_decision": {"1:1": 5.0, "1:2": 5.0}}, "louo": {"per_decision": {}}},
            "weights": {"F5_mal": 0.1}, "logged": {"total": 30, "1": 16, "2": 14}, "seconds": {},
        }

    monkeypatch.setattr(ev, "evaluate", evaluate)


@pytest.mark.parametrize("previous, minimums, verdict", [
    ([], (30, 14), "applied"),
    ([{"built_for": rc.version(), "report": _refit({"1:1": 4.0, "1:2": 4.0})}], (30, 14), "held"),
    ([{"built_for": "older code", "report": _refit({"1:1": 4.0, "1:2": 4.0})}], (30, 14), "applied"),
    ([], (31, 14), "waiting"),
    ([], (30, 15), "waiting"),
])
def test_the_weekly_verdict(stub_report, monkeypatch, previous, minimums, verdict):
    """Applied with nothing tripped; held when NLL rose by a whole nat since a run of this
    code, but not since one of older code; waiting while the log is short in all, or for any
    user with logged picks."""
    monkeypatch.setattr(ev, "MIN_LOG_PICKS", minimums[0])
    monkeypatch.setattr(ev, "MIN_USER_LOG_PICKS", minimums[1])
    summary = ev.weekly(_anime(), {}, math.inf, {}, [], {"F5_mal": 0.2}, previous, T0)
    assert summary["verdict"] == verdict
    assert summary["log"] == {"picks": 30, "needed": minimums[0], "per_user": {"1": 16, "2": 14}, "per_user_needed": minimums[1]}
    assert summary["report"]["weights"] == {"live": {"F5_mal": 0.2}, "refit": {"F5_mal": 0.1}}
