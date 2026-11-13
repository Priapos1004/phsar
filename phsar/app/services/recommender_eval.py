"""The recommender's harness: every user's natural history replayed pick by pick, the pooled
weights fitted, and both measured out of sample (docs/features/recommender.md, "Measuring
it"). `scripts/backtest_recommender.py` runs it.

App-free like `recommender_compute`, for the same reason.
"""

import math
import time
from collections import Counter, defaultdict
from typing import Any, NamedTuple

import numpy as np

from app.services import recommender_compute as rc

LAMBDA = 10.0  # L2 strength: the bake-off's inner CV chose it in every outer split
TRAIN_SHARE = 0.6  # each user's earliest decisions, which the time split trains on
PER_USER_LAMBDAS = (10.0, 100.0)  # how hard a per-user fit is pulled toward the pooled weights
FLIPS = 10_000  # random sign flips behind an ablation's p
AGE_EDGES = (7, 30, 90)  # days: the watchlist metrics' entry-age buckets
AGE_LABELS = ("<=7d", "8-30d", "31-90d", ">90d")


_FAMILY = np.array([rc.family(n) for n in rc.NAMES])
SHIPPED = ~np.isin(_FAMILY, rc.HARNESS)
# The similarity baseline the learned model has to beat: the recent picks plus closeness to
# the favourites, each already standardised within its decision.
BASELINE = rc.weight_vector({"F1_sim_decay10": 1.0, "F5_top20_sim": 1.0})


class Case(NamedTuple):
    """One natural pick and the candidates of its moment."""
    user: int
    t: float
    dec: rc.Decision
    target: int  # the pick's index among `dec.rows`
    liked: bool  # rated at or above the user's median
    caps: tuple[int, int]  # the row's caps from the history before it


def cases(cat: rc.Catalogue, ledgers: dict[int, rc.Ledger], harness: bool = True) -> list[Case]:
    """The decisions docs/features/recommender.md, "Measuring it", replays, in time order per
    user. `harness` computes the harness-only families too, which only a refit reads."""
    out = []
    for user, led in ledgers.items():
        median = float(np.median(led.rating)) if len(led.rating) else math.nan
        for j, e in enumerate(led.natural[rc.LAGS:], start=rc.LAGS):
            dec = rc.decide(cat, led, e.t, harness=harness)
            hit = np.flatnonzero(dec.rows == e.row)
            if len(hit):
                before = led._replace(pick_cont=led.pick_cont[:j], pick_listed=led.pick_listed[:j])
                out.append(Case(user, e.t, dec, int(hit[0]), e.rating >= median, rc.caps(before)))
    return out


def fit(chosen: list[Case], columns: np.ndarray, lam: float = LAMBDA, prior: np.ndarray | None = None) -> np.ndarray:
    """Conditional-logit weights over `columns`: the full softmax over each decision's
    candidates, plus `lam` · ‖w − prior‖² (prior zero, or the pooled weights for a per-user
    fit)."""
    from scipy.optimize import minimize

    w = np.zeros(len(rc.NAMES)) if prior is None else prior.copy()
    if not chosen:
        return w
    X = np.vstack([c.dec.X[:, columns] for c in chosen])
    sizes = np.array([len(c.dec.rows) for c in chosen])
    starts = np.r_[0, np.cumsum(sizes)[:-1]]
    picked = X[starts + np.array([c.target for c in chosen])].sum(axis=0)
    p0 = w[columns]

    def objective(v: np.ndarray) -> tuple[float, np.ndarray]:
        s = X @ v
        top = np.maximum.reduceat(s, starts)
        e = np.exp(s - np.repeat(top, sizes))
        z = np.add.reduceat(e, starts)
        loss = float((np.log(z) + top).sum() - picked @ v + lam * ((v - p0) ** 2).sum())
        return loss, X.T @ (e / np.repeat(z, sizes)) - picked + 2 * lam * (v - p0)

    w[columns] = minimize(objective, p0, jac=True, method="L-BFGS-B", options={"maxiter": 1000}).x
    return w


def nll(case: Case, w: np.ndarray) -> float:
    s = case.dec.X @ w
    top = s.max()
    return float(top + np.log(np.exp(s - top).sum()) - s[case.target])


def ranks(cat: rc.Catalogue, case: Case, w: np.ndarray, row: bool = True) -> tuple[int, int, int]:
    """The pick's rank under the logit alone, under the ranking's score (the enjoyment tilt
    added), and in the row the slate makes of that score (0 when `row` is off)."""
    logit = case.dec.X @ w
    score = rc.ranking_score(case.dec, w)
    in_row = 0
    if row:
        order, _ = rc.slate(score, case.dec, cat, *case.caps)
        in_row = int(np.flatnonzero(order == case.target)[0]) + 1
    return int((logit > logit[case.target]).sum()) + 1, int((score > score[case.target]).sum()) + 1, in_row


def metrics(r: np.ndarray, liked: np.ndarray) -> dict[str, Any]:
    if not len(r):
        return {"n": 0}
    hit = r <= rc.ROW
    return {
        "n": len(r), "median_rank": float(np.median(r)), "hit25": round(float(hit.mean()), 3),
        "liked_hit25": round(float(hit[liked].mean()), 3) if liked.any() else None, "n_liked": int(liked.sum()),
    }


def splits(chosen: list[Case]) -> dict[str, list[tuple[np.ndarray, np.ndarray]]]:
    """Train and test indices per split: docs/features/recommender.md, "Measuring it"."""
    users = np.array([c.user for c in chosen])
    out: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {"time": [], "louo": []}
    for u in dict.fromkeys(users.tolist()):
        own, others = np.flatnonzero(users == u), np.flatnonzero(users != u)
        cut = int(TRAIN_SHARE * len(own))
        out["time"].append((np.r_[own[:cut], others], own[cut:]))
        if len(others):
            out["louo"].append((others, own))
    return out


class HeldOut(NamedTuple):
    """Each test decision of one split, with its pick's ranks and NLL."""
    test: np.ndarray
    logit: np.ndarray
    score: np.ndarray
    row: np.ndarray
    nll: np.ndarray


def held_out(cat, chosen, folds, weights_of, row: bool = True) -> HeldOut:
    """`weights_of(train, test)` gives each fold's weights; its test decisions are ranked by
    them."""
    test: list[int] = []
    out: list[tuple[int, int, int]] = []
    losses: list[float] = []
    for train, te in folds:
        w = weights_of(train, te)
        test.extend(te.tolist())
        out.extend(ranks(cat, chosen[i], w, row) for i in te)
        losses.extend(nll(chosen[i], w) for i in te)
    r = np.array(out, dtype=np.int64).reshape(-1, 3)
    return HeldOut(np.array(test, dtype=np.int64), r[:, 0], r[:, 1], r[:, 2], np.array(losses))


def _report(h: HeldOut, liked: np.ndarray) -> dict[str, Any]:
    out = {
        "logit": metrics(h.logit, liked[h.test]), "score": metrics(h.score, liked[h.test]),
        "nll": round(float(h.nll.mean()), 4) if len(h.nll) else None,
    }
    if h.row.any():  # ranked in the row too
        out["row"] = metrics(h.row, liked[h.test])
    return out


def sign_flip_p(d: np.ndarray) -> float:
    """Two-sided p that paired differences `d` average zero."""
    if not len(d) or not d.any():
        return 1.0
    flips = np.random.default_rng(0).choice((-1.0, 1.0), size=(FLIPS, len(d)))
    return float((np.abs((flips * d).mean(axis=1)) >= abs(d.mean()) - 1e-12).mean())


def evaluate(
    cat: rc.Catalogue, ledgers: dict[int, rc.Ledger], weights: dict[str, float], *,
    refit: bool = False, lam: float = LAMBDA, now: float | None = None,
) -> dict[str, Any]:
    """The harness's report: docs/features/recommender.md, "Measuring it". Without `refit` it
    ranks only `weights` and the baseline, beside the watchlist metrics."""
    clock = time.perf_counter()
    chosen = cases(cat, ledgers, harness=refit)
    seconds = {"decisions": round(time.perf_counter() - clock, 1)}
    liked = np.array([c.liked for c in chosen], dtype=bool)
    folds = splits(chosen)
    users = [c.user for c in chosen]
    report: dict[str, Any] = {
        "decisions": {"total": len(chosen), **{str(u): users.count(u) for u in dict.fromkeys(users)}},
        "candidates_mean": round(float(np.mean([len(c.dec.rows) for c in chosen])), 1) if chosen else 0,
        "given": {}, "baseline": {},
    }
    given = rc.weight_vector(weights)
    for split, fs in folds.items():
        report["given"][split] = _report(held_out(cat, chosen, fs, lambda *_: given), liked)
        report["baseline"][split] = _report(held_out(cat, chosen, fs, lambda *_: BASELINE, row=False), liked)
    if refit:
        clock = time.perf_counter()
        report.update(_refit(cat, chosen, folds, liked, lam))
        seconds["fits"] = round(time.perf_counter() - clock, 1)
    report["watchlist"] = watchlist_metrics(cat, ledgers, chosen, time.time() if now is None else now)
    report["seconds"] = seconds
    return report


def _refit(cat, chosen, folds, liked, lam) -> dict[str, Any]:
    def by(columns):
        return lambda train, _: fit([chosen[i] for i in train], columns, lam)

    out: dict[str, Any] = {"refit": {}, "ablations": {}, "per_user": {}}
    full = {split: held_out(cat, chosen, fs, by(SHIPPED)) for split, fs in folds.items()}
    for split, h in full.items():
        out["refit"][split] = _report(h, liked)

    def fitted(columns, split):
        if np.array_equal(columns, SHIPPED):
            return full[split]
        return held_out(cat, chosen, folds[split], by(columns), row=False)

    variants = {f: (SHIPPED & (f != _FAMILY), SHIPPED) for f in dict.fromkeys(_FAMILY[SHIPPED])}
    variants["W_backlog"] = (SHIPPED & (np.array(rc.NAMES) != "W_backlog"), SHIPPED)
    variants.update({f: (SHIPPED, SHIPPED | (f == _FAMILY)) for f in rc.HARNESS})
    for name, (without, with_) in variants.items():
        out["ablations"][name] = {}
        for split in folds:
            a, b = fitted(without, split), fitted(with_, split)
            out["ablations"][name][split] = {
                "hit25": round(float((b.logit <= rc.ROW).mean() - (a.logit <= rc.ROW).mean()), 3),
                "nll": round(float((a.nll - b.nll).mean()), 4), "p": round(sign_flip_p(a.nll - b.nll), 3),
            }
    for lam_u in PER_USER_LAMBDAS:
        def per_user(train, test, lam_u=lam_u):
            own = [chosen[i] for i in train if chosen[i].user == chosen[test[0]].user]
            return fit(own, SHIPPED, lam_u, prior=fit([chosen[i] for i in train], SHIPPED, lam))

        h = held_out(cat, chosen, [f for f in folds["time"] if len(f[1])], per_user, row=False)
        out["per_user"][str(lam_u)] = _report(h, liked)
    w = fit(chosen, SHIPPED, lam)
    out["weights"] = {name: round(float(v), 4) for name, v in zip(rc.NAMES, w, strict=True) if SHIPPED[rc.COLUMN[name]]}
    return out


# --- The watchlist ---------------------------------------------------------------------------

def _age(days: np.ndarray) -> np.ndarray:
    return np.digitize(days, AGE_EDGES, right=True)


def watchlist_metrics(cat: rc.Catalogue, ledgers: dict[int, rc.Ledger], chosen: list[Case], now: float) -> dict[str, Any]:
    """The watchlist metrics, per user and pooled: docs/features/recommender.md, "Measuring
    it". The hazard is picks per 100 listed-anime-days."""
    picks: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    expected: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    converted: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    exposure: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    share: dict[str, list[float]] = defaultdict(list)

    def add(store, user, key, value=1.0):
        store[str(user)][key] += value
        store["pooled"][key] += value

    for case in chosen:
        led = ledgers[case.user]
        if case.t < led.listed_from:
            continue
        active, _, touched = rc.listing(cat, led, case.t)
        tags: dict[int, set] = defaultdict(set)
        for p, _, _, tag in active:
            tags[int(cat.media_row[p])].add(tag)
        C = case.dec.rows
        pr, age = case.dec.priority, _age((case.t - touched[C]) / rc.DAY)
        r = case.target
        n = len(C)
        for level in (0, 1, 2, 3):
            add(expected, case.user, ("priority", level), float((pr == level).sum()) / n)
        add(picks, case.user, ("priority", int(pr[r])))
        for b in range(len(AGE_LABELS)):
            add(expected, case.user, ("age", b), float(((pr > 0) & (age == b)).sum()) / n)
        if pr[r]:
            add(picks, case.user, ("age", int(age[r])))
        for tag, k in Counter(t for row in C.tolist() for t in tags.get(row, ())).items():
            add(expected, case.user, ("list", tag), k / n)
        for tag in tags.get(int(C[r]), ()):
            add(picks, case.user, ("list", tag))

    for user, led in ledgers.items():
        if math.isinf(led.listed_from):
            continue
        known = ~np.isnan(led.pick_listed)
        share[str(user)] = led.pick_listed[known].tolist()
        share["pooled"].extend(led.pick_listed[known].tolist())
        for day in np.arange(math.floor(led.listed_from / rc.DAY), math.floor(now / rc.DAY)):
            t = (day + 0.5) * rc.DAY
            _, priority, touched = rc.listing(cat, led, t)
            on = np.flatnonzero(priority)
            for prio, b in zip(priority[on].tolist(), _age((t - touched[on]) / rc.DAY).tolist(), strict=True):
                add(exposure, user, ("priority", prio))
                add(exposure, user, ("age", b))
        for e in led.natural:
            if e.t < led.listed_from:
                continue
            _, priority, touched = rc.listing(cat, led, e.t)
            if priority[e.row]:
                add(converted, user, ("priority", int(priority[e.row])))
                add(converted, user, ("age", int(_age((e.t - touched[e.row]) / rc.DAY))))

    def label(kind, key):
        return AGE_LABELS[key] if kind == "age" else ("unlisted" if kind == "priority" and key == 0 else str(key))

    out: dict[str, Any] = {}
    for group in share:
        lift: dict[str, dict] = defaultdict(dict)
        for kind, key in sorted(expected[group], key=str):
            got, exp = picks[group][(kind, key)], expected[group][(kind, key)]
            lift[kind][label(kind, key)] = {"lift": round(got / exp, 2) if exp else None, "picks": int(got)}
        hazard: dict[str, dict] = defaultdict(dict)
        for kind, key in sorted(exposure[group], key=str):
            days, got = exposure[group][(kind, key)], converted[group][(kind, key)]
            hazard[kind][label(kind, key)] = {"per_100_days": round(100 * got / days, 2), "picks": int(got), "days": int(days)}
        values = share[group]
        out[group] = {
            "picks": len(values), "listed_share": round(float(np.mean(values)), 3) if values else None,
            "lift": lift, "hazard": hazard,
        }
    return out
