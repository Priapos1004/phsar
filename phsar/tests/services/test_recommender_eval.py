"""`recommender_eval` and the backtest's backup diff on synthetic data: the fit recovers what
drew the picks, the splits keep each test decision out of its own training, and the watchlist
metrics' arithmetic. What the harness measures on the prod data is a study, not a test."""

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
    dec = rc.Decision(np.arange(n), X, np.zeros(n), np.zeros(n, bool), empty, np.zeros(n, bool), empty, empty, np.zeros(n))
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
    """The harness end to end on a small history: every family ablated, and the fit's
    weights cover the shipped features alone."""
    cat = _anime(n=40)
    ledgers = {
        u: rc.ledger(cat, [_rating(m, T0 + d * DAY) for d, m in enumerate(range(first, first + 8))], [])
        for u, first in ((1, 1), (2, 20))
    }
    report = ev.evaluate(cat, ledgers, rc.WEIGHTS, refit=True, now=T0 + 10 * DAY)
    assert report["decisions"] == {"total": 10, "1": 5, "2": 5}
    assert set(report["ablations"]) == {*dict.fromkeys(ev._FAMILY), "W_backlog"}
    assert set(report["weights"]) == {n for n in rc.NAMES if rc.family(n) not in rc.HARNESS}
    assert report["refit"]["louo"]["row"]["n"] == 10
