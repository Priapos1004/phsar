"""The recommender's harness: every user's natural history replayed pick by pick, the pooled
weights fitted, and both measured out of sample (docs/features/recommender.md, "Measuring
it"). `scripts/backtest_recommender.py` runs it, and the weekly `recommender_eval` job runs
`weekly`, which adds what only the job reports.

App-free like `recommender_compute`, for the same reason.
"""

import math
import time
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any, NamedTuple

import numpy as np

from app.services import recommender_compute as rc
from app.services.galaxy_compute import distances

LAMBDA = 10.0  # L2 strength: the bake-off's inner CV chose it in every outer split
TRAIN_SHARE = 0.6  # each user's earliest decisions, which the time split trains on
PER_USER_LAMBDAS = (10.0, 100.0)  # how hard a per-user fit is pulled toward the pooled weights
FLIPS = 10_000  # random sign flips behind an ablation's p
AGE_EDGES = (7, 30, 90)  # days: the watchlist metrics' entry-age buckets
AGE_LABELS = ("<=7d", "8-30d", "31-90d", ">90d")
REWATCH_FEATURES = ("own_pct", "recent_sim", "recent_genres", "rewatched")  # the rewatch family's columns
REWATCH_TOP = 10  # a complete rewatch's hit@k: a rewatch slot would be a few tiles of the row
PICKS_AFTER = 5  # the user's next picks a shown anime is judged within (`online`)

# --- The weekly job: docs/features/recommender.md, "The weekly job". Measured on the prod
# history: the compound doc.
MIN_LOG_PICKS, MIN_USER_LOG_PICKS = 30, 14  # decisions that see the watchlist, in all and per user with any
FLIP_ABOVE = 0.2  # a live weight this large must not change sign
# How far held-out NLL may rise over the decisions two runs share. The floor because those runs
# share nearly every decision, so the standard error alone shrinks until ordinary drift trips it.
NOISE_SE, NOISE_FLOOR = 2, 0.05
HELP_RUNS, HELP_P = 3, 0.05  # "would help now": beyond noise in this many runs in a row


_FAMILY = np.array([rc.family(n) for n in rc.NAMES])
SHIPPED = np.isin(rc.NAMES, list(rc.WEIGHTS))
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


def fit(chosen: Sequence["Case | Rewatch"], columns: np.ndarray, lam: float = LAMBDA, prior: np.ndarray | None = None) -> np.ndarray:
    """Conditional-logit weights over `columns`, a mask over the decisions' features: the full
    softmax over each decision's candidates, plus `lam` · ‖w − prior‖² (prior zero, or the
    pooled weights for a per-user fit)."""
    from scipy.optimize import minimize

    w = np.zeros(len(columns)) if prior is None else prior.copy()
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


def splits(chosen: Sequence["Case | Rewatch"]) -> dict[str, list[tuple[np.ndarray, np.ndarray]]]:
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


def _se(x: np.ndarray) -> float:
    """The standard error of `x`'s mean."""
    return float(x.std(ddof=1) / math.sqrt(len(x)))


def _report(h: HeldOut, liked: np.ndarray) -> dict[str, Any]:
    out = {
        "logit": metrics(h.logit, liked[h.test]), "score": metrics(h.score, liked[h.test]),
        "nll": round(float(h.nll.mean()), 4) if len(h.nll) else None,
        "nll_se": round(_se(h.nll), 4) if len(h.nll) > 1 else None,
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
    def per_user(users: list[int]) -> dict[str, int]:
        return {"total": len(users), **{str(u): n for u, n in Counter(users).items()}}

    report: dict[str, Any] = {
        "decisions": per_user([c.user for c in chosen]),
        # Those that see the watchlist: only they say anything about its weights.
        "logged": per_user([c.user for c in chosen if c.t >= ledgers[c.user].listed_from]),
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
        # Each test decision's NLL by who picked when, so the next run can compare the decisions
        # both tested (`guards`).
        per_decision = {
            f"{chosen[i].user}:{round(chosen[i].t)}": round(float(v), 4) for i, v in zip(h.test.tolist(), h.nll, strict=True)
        }
        out["refit"][split] = {**_report(h, liked), "per_decision": per_decision}

    def fitted(columns, split):
        if np.array_equal(columns, SHIPPED):
            return full[split]
        return held_out(cat, chosen, folds[split], by(columns), row=False)

    variants = {f: (SHIPPED & (f != _FAMILY), SHIPPED) for f in dict.fromkeys(_FAMILY[SHIPPED])}
    variants["W_backlog"] = (SHIPPED & (np.array(rc.NAMES) != "W_backlog"), SHIPPED)
    variants.update({
        f if f in rc.HARNESS else f"{f}_unranked": (SHIPPED, SHIPPED | (f == _FAMILY))
        for f in dict.fromkeys(_FAMILY[~SHIPPED])
    })
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
    # Two decimals: rounding there moves no held-out metric, and the digits below are noise.
    out["weights"] = {name: round(float(v), 2) for name, v in zip(rc.NAMES, w, strict=True) if SHIPPED[rc.COLUMN[name]]}
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


# --- Complete rewatches ----------------------------------------------------------------------

class Scored(NamedTuple):
    """A decision as `fit` and `nll` read it."""
    rows: np.ndarray
    X: np.ndarray


class Rewatch(NamedTuple):
    """One complete rewatch and the user's finished, unlisted anime at its moment."""
    user: int
    t: float
    dec: Scored  # its columns are `REWATCH_FEATURES`
    target: int


def rewatch_runs(cat: rc.Catalogue, led: rc.Ledger, watches: list[tuple[int, float]]) -> tuple[list[tuple[float, int]], list[tuple[float, int]]]:
    """A user's rewatches as (time, star row), from their watch events `(media_id, at)` in order:
    every watch of a media after its first. The natural ones as runs, a rewatch right after a
    pick of the same anime merged into it (which are natural: docs/features/recommender.md,
    "The weekly job"), and every one, an import's included, which says only that it was
    rewatched by then."""
    seen: set[int] = set()
    every = []
    for media_id, at in watches:
        if media_id in seen and media_id in cat.position_of:
            every.append((at, int(cat.media_row[cat.position_of[media_id]])))
        seen.add(media_id)
    if led.start is None:
        return [], every
    natural_days = {rc._day(e.t) for e in led.natural}
    imports = {d for d in np.floor(led.t / rc.DAY).astype(np.int64).tolist() if d >= led.start} - natural_days
    picks = sorted(
        [(e.t, e.row, False) for e in led.natural]
        + [(t, row, True) for t, row in every if (d := rc._day(t)) >= led.start and d not in imports]
    )
    runs = []
    for (t, row, rewatch), previous in zip(picks, [None, *picks[:-1]], strict=True):
        if rewatch and (previous is None or previous[1] != row):
            runs.append((t, row))
    return runs, every


def rewatch_cases(
    cat: rc.Catalogue, ledgers: dict[int, rc.Ledger],
    runs: dict[int, tuple[list[tuple[float, int]], list[tuple[float, int]]]],
) -> list[Rewatch]:
    """Each complete rewatch as a decision among its candidates; which count:
    docs/features/recommender.md, "The weekly job". A refresh before a sequel is a continuation
    and a listed rewatch is in the ranking, so neither is one."""
    out = []
    for user, led in ledgers.items():
        natural, every = runs.get(user, ([], []))
        every_t = np.array([t for t, _ in every], dtype=float)
        every_row = np.array([row for _, row in every], dtype=np.int64)
        for t, row in natural:
            before = led.t < t
            rated, status = led.position[before], led.status[before]
            _, priority, _ = rc.listing(cat, led, t)
            C = np.flatnonzero(rc.state(cat, t, rated, status).finished & (priority == 0))
            hit = np.flatnonzero(row == C)
            if not len(hit):
                continue
            _, own = rc.own_percentiles(cat, rated, led.rating[before], status == "dropped")
            X = np.zeros((len(C), len(REWATCH_FEATURES)))
            X[:, 0] = own[C]
            latest = np.array([e.row for e in led.natural if e.t < t][::-1][:rc.RECENT], dtype=np.int64)
            if len(latest):
                D = distances(cat.features[latest], cat.uncertainty[latest], cat.features[C], cat.uncertainty[C])
                X[:, 1] = rc.decayed(rc.recent_ranks(D, latest, C))
                X[:, 2] = np.mean([rc.genre_jaccard(cat.genres[C], cat.genres[p]) for p in latest], axis=0)
            X[:, 3] = np.isin(C, every_row[every_t < t])
            out.append(Rewatch(user, t, Scored(C, np.stack([rc._z(x) for x in X.T], axis=1)), int(hit[0])))
    return out


def rewatch_report(chosen: list[Rewatch]) -> dict[str, Any]:
    """The rewatch family fitted on each split's training rewatches, against plain own-score
    order on its test ones: hit@`REWATCH_TOP`, median rank, and a paired sign-flip p on the
    log ranks."""
    out: dict[str, Any] = {
        "decisions": len(chosen),
        "candidates_mean": round(float(np.mean([len(c.dec.rows) for c in chosen])), 1) if chosen else 0,
    }

    def top(r: np.ndarray) -> dict[str, float]:
        return {"hit10": round(float((r <= REWATCH_TOP).mean()), 3), "median_rank": float(np.median(r))}

    def rank(s: np.ndarray, target: int) -> float:
        """The target's place with ties at their mean: own scores tie a lot, and breaking
        every tie its way would flatter the plain order."""
        return float(rc._rank(-s)[target])

    for split, folds in splits(chosen).items():
        family, plain = [], []
        for train, test in folds:
            w = fit([chosen[i] for i in train], np.ones(len(REWATCH_FEATURES), dtype=bool))
            for i in test.tolist():
                c = chosen[i]
                family.append(rank(c.dec.X @ w, c.target))
                plain.append(rank(c.dec.X[:, 0], c.target))  # own percentile alone: the plain order
        f, p = np.array(family), np.array(plain)
        out[split] = {
            "n": len(f), "family": top(f), "own_score": top(p), "p": round(sign_flip_p(np.log(p) - np.log(f)), 3),
        } if len(f) else {"n": 0}
    return out


# --- Online --------------------------------------------------------------------------------------

def online(
    cat: rc.Catalogue, ledgers: dict[int, rc.Ledger], runs: dict[int, list[tuple[float, int]]],
    exposure: list[tuple[int, int, str, float]],
) -> dict[str, Any]:
    """The row's watch-through by reason, over the stretches `exposure` logged — `(user,
    anime, kind, opened at)` — and each user's natural picks, first watches and rewatch runs
    alike."""
    picks = {u: sorted([(e.t, e.row) for e in led.natural] + runs.get(u, [])) for u, led in ledgers.items()}
    times = {u: [t for t, _ in ps] for u, ps in picks.items()}
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    waiting = 0
    for user, anime_id, kind, opened in exposure:
        row = cat.row_of.get(anime_id)
        if row is None:
            continue
        i = bisect_right(times.get(user, []), opened)
        after = [r for _, r in picks.get(user, [])[i:i + PICKS_AFTER]]
        if row not in after and len(after) < PICKS_AFTER:
            waiting += 1
            continue
        tally[kind][0] += 1
        tally[kind][1] += row in after
    return {
        "judged": sum(j for j, _ in tally.values()), "waiting": waiting,
        "by_reason": {k: {"judged": j, "watched": w, "share": round(w / j, 3)} for k, (j, w) in sorted(tally.items())},
    }


# --- The weekly job ------------------------------------------------------------------------------

def guards(report: dict[str, Any], live: dict[str, float], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    """What holds a refit back. The NLL checks are listed whether they trip or not, to show how
    near a run came; a flip only when it trips, since the summary's weights show the rest."""
    out: list[dict[str, Any]] = []
    before = previous["report"]["refit"] if previous else {}
    for split, now in report["refit"].items():
        mine, then = now["per_decision"], before.get(split, {}).get("per_decision", {})
        d = np.array([mine[k] - then[k] for k in sorted(mine.keys() & then.keys())])
        if len(d) < 2:
            continue
        change = float(d.mean())
        margin = max(NOISE_SE * _se(d), NOISE_FLOOR)
        out.append({
            "kind": "nll", "split": split, "change": round(change, 4), "margin": round(margin, 4), "n": len(d),
            "tripped": change > margin,
        })
    for name, w in report["weights"]["refit"].items():
        old = live.get(name, 0.0)
        if abs(old) > FLIP_ABOVE and old * w < 0:
            out.append({"kind": "flip", "name": name, "live": old, "refit": w, "tripped": True})
    return out


def _helped(report: dict[str, Any]) -> set[str]:
    """The left-out families this run found helping beyond noise on both splits."""
    out = set()
    for name, by_split in report["ablations"].items():
        added = name in rc.HARNESS or name.endswith("_unranked")
        if added and all(s["nll"] > 0 and s["p"] < HELP_P for s in by_split.values()):
            out.add(name)
    rewatch = [report["rewatch"][split] for split in ("time", "louo")]
    if all(s["n"] and s["family"]["hit10"] > s["own_score"]["hit10"] and s["p"] < HELP_P for s in rewatch):
        out.add("rewatch")
    return out


def would_help(report: dict[str, Any], previous: list[dict[str, Any]]) -> list[str]:
    """The left-out families that helped beyond noise in this run and the `HELP_RUNS` − 1 before
    it (`previous`, their reports, newest first): one good run is noise, a streak is a case for
    shipping the family."""
    if len(previous) < HELP_RUNS - 1:
        return []
    return sorted(set.intersection(*(_helped(r) for r in [report, *previous[:HELP_RUNS - 1]])))


def weekly(
    cat: rc.Catalogue, histories: dict[int, tuple[list[rc.RatingRow], list[rc.ListingRow], dict]], listed_from: float,
    watches: dict[int, list[tuple[int, float]]], exposure: list[tuple[int, int, str, float]],
    live: dict[str, float], previous: list[dict[str, Any]], now: float,
) -> dict[str, Any]:
    """The weekly job's summary: the harness's report on the live weights with a refit, the
    rewatch family and the row's watch-through, the guards over the refit, and the verdict.
    `histories` are each user's ratings, listings and franchise signals as
    `rc.ledger` takes them; `previous` the last runs' summaries, newest first, of which only
    those for this code compare."""
    ledgers = {
        u: rc.ledger(cat, ratings, listings, franchise=franchise, listed_from=listed_from)
        for u, (ratings, listings, franchise) in histories.items()
    }
    previous = [p for p in previous if p.get("built_for") == rc.version()]
    report = evaluate(cat, ledgers, live, refit=True, now=now)
    clock = time.perf_counter()
    runs = {u: rewatch_runs(cat, led, watches.get(u, [])) for u, led in ledgers.items()}
    report["rewatch"] = rewatch_report(rewatch_cases(cat, ledgers, runs))
    report["online"] = online(cat, ledgers, {u: natural for u, (natural, _) in runs.items()}, exposure)
    report["seconds"]["rewatch_online"] = round(time.perf_counter() - clock, 1)
    report["weights"] = {"live": dict(live), "refit": report["weights"]}
    logged = report.pop("logged")
    total = logged.pop("total")
    checks = guards(report, live, previous[0] if previous else None)
    if total < MIN_LOG_PICKS or any(k < MIN_USER_LOG_PICKS for k in logged.values()):
        verdict = "waiting"
    elif any(g["tripped"] for g in checks):
        verdict = "held"
    else:
        verdict = "applied"
    return {
        "verdict": verdict, "guards": checks, "built_for": rc.version(),
        "log": {"picks": total, "needed": MIN_LOG_PICKS, "per_user": logged, "per_user_needed": MIN_USER_LOG_PICKS},
        "would_help": would_help(report, [p["report"] for p in previous]),
        "report": report,
    }
