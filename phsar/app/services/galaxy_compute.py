"""The galaxy map's numerics: per-anime feature vectors, the fit (UMAP to 10-D, HDBSCAN
sectors, Ward regions inside each sector, a 2-D layout of the 10-D space) and placement of
new anime onto a fitted map.

It imports nothing from the app, and the fitting libraries only inside `fit` and `place`,
so a spawned child (`galaxy_service.run_in_child`) can load it alone and the web process
can import its row types and `carry_names` without loading them. The rows arrive with the
app's own definitions already resolved (`GalaxyDAO.load_catalogue`).

Every constant below was chosen on the prod catalogue:
compound-docs/2026-10-30-v0.16.5-galaxy.md.
"""

import pickle
from collections import Counter, defaultdict
from typing import Any, NamedTuple

import numpy as np

# Block weights. Each block is scaled so its mean squared pairwise distance over the
# training set is 1, then multiplied by sqrt(weight): the squared distance between two
# feature vectors is then the weighted sum of the blocks' squared distances.
WEIGHTS = {
    "desc": 4.0, "genres": 2.0, "themes": 2.0, "demographics": 0.7, "source": 0.5,
    "format": 0.5, "age": 0.3, "era": 0.3, "studios": 0.3, "quality": 0.5,
}
TAG_GROUPS = {
    "genres": ("genres", "explicit_genres"), "themes": ("themes",), "demographics": ("demographics",),
}
TOP_STUDIOS = 25
ERA = (1970, 2027)
SEED = 42
# Sectors: HDBSCAN on the 10-D layout (on the raw vectors it calls most stars noise).
# The size cap stops excess-of-mass from collapsing into one giant sector.
MIN_SECTOR, MIN_SAMPLES, MAX_SECTOR_FRACTION = 25, 5, 6
# Below this many anime the cap leaves no room for a sector, so no fit is tried.
MIN_CATALOGUE = MIN_SECTOR * MAX_SECTOR_FRACTION
REGION_SIZE = 30
# A hand name follows the new group sharing at least this much (Jaccard) of its old
# trained members; below it the group shows its auto name.
NAME_FLOOR = 0.4


class MediaRow(NamedTuple):
    anime_id: int
    main: bool  # in `MAIN_STORY_RELATIONS`
    settled: bool  # finished airing, with a MAL score
    media_type: str
    age: int | None  # `Media.age_rating_numeric`
    source: str | None
    watch_seconds: int | None  # `Media.total_watch_time`
    season_year: int | None
    tags: tuple[tuple[str, str], ...]  # (genre name, genre type)
    studios: tuple[str, ...]


class AnimeRow(NamedTuple):
    anime_id: int
    desc: list[float]  # the stored description embedding
    score: float | None  # the anime's MAL score and votes, as the app shows them
    votes: float | None


def _unit(X: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(X, axis=1, keepdims=True)
    return X / np.where(n == 0, 1, n)


def _shares(values: list[str]) -> dict[str, float]:
    return {k: c / len(values) for k, c in Counter(values).items()} if values else {}


def _profiles(anime: list[AnimeRow], media: list[MediaRow]) -> list[dict[str, Any]]:
    """Each anime's aggregates: source, format, studios and year over its main story; tags,
    age and watch time over every media, tag shares as the majority rule measures them."""
    by_anime: dict[int, list[MediaRow]] = defaultdict(list)
    for m in media:
        by_anime[m.anime_id].append(m)
    out = []
    for a in anime:
        ms = by_anime.get(a.anime_id, [])
        main = [m for m in ms if m.main]
        ages = [m.age for m in ms if m.age is not None]
        years = [m.season_year for m in main if m.season_year]
        tag_counts = Counter(tag for m in ms for tag in set(m.tags))
        sources = _shares([m.source for m in main if m.source])
        out.append({
            "tags": {tag: c / len(ms) for tag, c in tag_counts.items()},
            "source": sources,
            "format": _shares([m.media_type for m in main]),
            "studios": {s for m in main for s in m.studios},
            "watch_hours": sum(m.watch_seconds or 0 for m in ms) / 3600,
            "age": max(ages, default=None),
            "year": min(years) if years else None,
            "score": a.score,
            "votes": a.votes,
            # Settled: the main story has a finished media with a score. Everything else
            # is placed onto the map rather than shaping it.
            "trained": any(m.settled for m in main),
            "majority_tags": sorted(name for (name, _), c in tag_counts.items() if c / len(ms) > 0.5),
            "top_source": max(sources, key=sources.__getitem__) if sources else None,
        })
    return out


def _fit_stats(profiles: list[dict[str, Any]], train: np.ndarray) -> dict[str, Any]:
    """Column sets and fill values, read off the training anime and kept for placement."""
    trained = [p for p, t in zip(profiles, train, strict=True) if t]
    made = Counter(s for p in trained for s in p["studios"])
    studios = sorted({s for p in profiles for s in p["studios"]})
    output = np.array([made.get(s, 0) for s in studios] or [0])
    cut50, cut90 = (float(q) for q in np.quantile(output, [0.5, 0.9]))
    return {
        "tags": {
            group: sorted({name for p in profiles for name, kind in p["tags"] if kind in kinds})
            for group, kinds in TAG_GROUPS.items()
        },
        "sources": sorted({s for p in profiles for s in p["source"]}),
        "formats": sorted({f for p in profiles for f in p["format"]}),
        "top_studios": [s for s, _ in sorted(made.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_STUDIOS]],
        "studio_output": dict(made),
        "studio_cuts": (cut50, cut90),
        "medians": {
            key: float(np.median([p[key] for p in trained if p[key] is not None] or [0]))
            for key in ("age", "year", "score")
        },
    }


def _studio_size(stats: dict[str, Any], studio: str) -> int:
    made = stats["studio_output"].get(studio, 0)
    cut50, cut90 = stats["studio_cuts"]
    return 2 if made >= cut90 else 1 if made >= cut50 else 0


def _raw_blocks(profiles: list[dict[str, Any]], desc: np.ndarray, stats: dict[str, Any]) -> dict[str, np.ndarray]:
    n = len(profiles)
    med = stats["medians"]

    def shares(columns: list[str], lookup) -> np.ndarray:
        M = np.zeros((n, len(columns)), np.float32)
        for i, p in enumerate(profiles):
            for j, c in enumerate(columns):
                M[i, j] = lookup(p, c)
        return M

    blocks = {
        group: shares(cols, lambda p, c, kinds=TAG_GROUPS[group]: sum(p["tags"].get((c, k), 0.0) for k in kinds))
        for group, cols in stats["tags"].items()
    }
    top = stats["top_studios"]
    studios = np.zeros((n, len(top) + 3), np.float32)
    for i, p in enumerate(profiles):
        for s in p["studios"]:
            if s in top:
                studios[i, top.index(s)] = 1
            else:
                studios[i, len(top) + _studio_size(stats, s)] = 1
    col = lambda v: np.asarray(v, np.float32).reshape(-1, 1)  # noqa: E731
    year = np.clip([p["year"] or med["year"] for p in profiles], *ERA)
    return {
        "desc": desc,
        **blocks,
        "source": shares(stats["sources"], lambda p, c: p["source"].get(c, 0.0)),
        "format": np.hstack([
            shares(stats["formats"], lambda p, c: p["format"].get(c, 0.0)),
            col(np.log1p([p["watch_hours"] for p in profiles])),
        ]),
        "age": col([(p["age"] if p["age"] is not None else med["age"]) / 18 for p in profiles]),
        "era": col((year - ERA[0]) / (ERA[1] - ERA[0])),
        "studios": studios,
        "quality": np.hstack([
            col([p["score"] if p["score"] is not None else med["score"] for p in profiles]),
            col(np.log1p([p["votes"] or 0 for p in profiles])),
        ]),
    }


def _features(raw: dict[str, np.ndarray], stats: dict[str, Any]) -> np.ndarray:
    return np.hstack([
        np.sqrt(w) * raw[k] / stats["scales"][k] for k, w in WEIGHTS.items()
    ]).astype(np.float32)


def _z(values: list[float | None]) -> tuple[float, float]:
    v = np.array([x for x in values if x is not None], dtype=float)
    return (float(v.mean()), float(v.std() or 1.0)) if len(v) else (0.0, 1.0)


def _quality_era(profiles: list[dict[str, Any]], m: dict[str, Any]) -> np.ndarray:
    """MAL score and era, z-scored (the mean when missing): what a sector's region space
    adds to its 10-D layout, so a sector splits by quality and age as well as by content."""
    (s_mu, s_sd), (e_mu, e_sd) = m["score_z"], m["era_z"]
    return np.array([
        [0.0 if p["score"] is None else (p["score"] - s_mu) / s_sd,
         0.0 if p["year"] is None else (p["year"] - e_mu) / e_sd]
        for p in profiles
    ]).reshape(-1, 2)


def _predict(
    m: dict[str, Any], X: np.ndarray, extra: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Where anime the fit did not train on land: through both layouts, into the sector
    HDBSCAN predicts (its likeliest when it answers noise, which draws them between
    regions) and the nearest region centroid there."""
    import hdbscan

    Z = m["u10"].transform(X)
    Y = m["u2"].transform(Z)
    labels, _ = hdbscan.approximate_predict(m["sectors"], Z)
    member = hdbscan.prediction.membership_vector(m["sectors"], Z).reshape(len(X), -1)
    sector = np.where(labels >= 0, labels, member.argmax(1))
    region = np.empty(len(X), int)
    for s in np.unique(sector):
        idx = np.flatnonzero(sector == s)
        divisor, centroids, offset = m["regions"][int(s)]
        F = np.hstack([Z[idx] / divisor, extra[idx]])
        region[idx] = ((F[:, None, :] - centroids[None]) ** 2).sum(-1).argmin(1) + offset
    return Z, Y, sector, region, labels < 0


def _stars(anime: list[AnimeRow], X, Z, Y, sector, region, between, trained) -> list[dict[str, Any]]:
    return [
        {
            "anime_id": a.anime_id, "x": float(Y[i, 0]), "y": float(Y[i, 1]), "z10": Z[i].tolist(),
            "sector": int(sector[i]), "region": int(region[i]), "between": bool(between[i]),
            "trained": bool(trained[i]), "features": X[i].tolist(),
        }
        for i, a in enumerate(anime)
    ]


def fit(anime: list[AnimeRow], media: list[MediaRow],
        previous: dict[int, tuple[list[float], list[float]]]) -> dict[str, Any]:
    """Fit a map. `previous` maps anime id to its (2-D, 10-D) coordinates on the live map,
    empty for a first fit; both layouts start from them (docs/features/galaxy.md)."""
    import hdbscan
    import umap
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.neighbors import NearestNeighbors

    profiles = _profiles(anime, media)
    train = np.array([p["trained"] for p in profiles])
    stats = _fit_stats(profiles, train)
    desc = _unit(np.asarray([a.desc for a in anime], np.float32))
    raw = _raw_blocks(profiles, desc, stats)
    stats["scales"] = {
        k: float(np.sqrt(2 * v.var(0).sum())) or 1.0 for k, v in ((k, raw[k][train]) for k in WEIGHTS)
    }
    X = _features(raw, stats)
    n = int(train.sum())

    known = np.array([a.anime_id in previous for a in anime])
    Y0 = np.full((len(anime), 2), np.nan)
    Z0 = np.full((len(anime), 10), np.nan)
    for i in np.flatnonzero(known):
        Y0[i], Z0[i] = previous[anime[i].anime_id]
    init10: Any = "spectral"
    init2: Any = "spectral"
    if known.any():
        fresh = train & ~known
        if fresh.any():
            _, nn = NearestNeighbors(n_neighbors=min(5, int(known.sum()))).fit(X[known]).kneighbors(X[fresh])
            Y0[fresh] = Y0[known][nn].mean(1)
            Z0[fresh] = Z0[known][nn].mean(1)
        init10, init2 = Z0[train], Y0[train]

    # A seed makes UMAP single-threaded; saying so (n_jobs=1) is what keeps it from warning.
    u10 = umap.UMAP(n_components=10, n_neighbors=15, min_dist=0.0, random_state=SEED, n_jobs=1, init=init10).fit(X[train])
    Zt = u10.embedding_
    sectors = hdbscan.HDBSCAN(
        min_cluster_size=MIN_SECTOR, min_samples=MIN_SAMPLES, prediction_data=True,
        max_cluster_size=max(n // MAX_SECTOR_FRACTION, MIN_SECTOR + 1),
    ).fit(Zt)
    k = int(sectors.labels_.max()) + 1
    if k == 0:
        raise ValueError("HDBSCAN found no sectors — the live map is kept")
    soft = hdbscan.all_points_membership_vectors(sectors).reshape(n, -1)
    sector_t = np.where(sectors.labels_ >= 0, sectors.labels_, soft.argmax(1))

    m: dict[str, Any] = {
        "score_z": _z([p["score"] for p in profiles]),
        "era_z": _z([p["year"] for p in profiles]),
        "regions": {},
    }
    extra = _quality_era(profiles, m)
    region_t = np.empty(n, int)
    parents: list[int] = []
    offset = 0
    for s in range(k):
        t = np.flatnonzero(sector_t == s)
        divisor = float(Zt[t].std(0).mean()) or 1.0
        F = np.hstack([Zt[t] / divisor, extra[train][t]])
        parts = max(1, round(len(t) / REGION_SIZE))
        sub = AgglomerativeClustering(n_clusters=parts).fit_predict(F) if parts > 1 else np.zeros(len(t), int)
        m["regions"][s] = (divisor, np.stack([F[sub == j].mean(0) for j in range(parts)]), offset)
        region_t[t] = sub + offset
        parents += [s] * parts
        offset += parts

    u2 = umap.UMAP(n_components=2, n_neighbors=15, min_dist=0.3, random_state=SEED, n_jobs=1, init=init2).fit(Zt)
    m.update(u10=u10, u2=u2, sectors=sectors, stats=stats)

    Z = np.empty((len(anime), 10), np.float32)
    Y = np.empty((len(anime), 2), np.float32)
    sector = np.empty(len(anime), int)
    region = np.empty(len(anime), int)
    between = np.empty(len(anime), bool)
    Z[train], Y[train], sector[train], region[train], between[train] = (
        Zt, u2.embedding_, sector_t, region_t, sectors.labels_ < 0,
    )
    if not train.all():
        Z[~train], Y[~train], sector[~train], region[~train], between[~train] = _predict(m, X[~train], extra[~train])

    groups = []
    everyone = np.arange(len(anime))
    for s in range(k):
        members = np.where(sector == s)[0]
        groups.append(_group("sector", s, None, members, everyone, anime, profiles, train, Y))
    for r, parent in enumerate(parents):
        members = np.where(region == r)[0]
        groups.append(_group("region", r, parent, members, np.where(sector == parent)[0], anime, profiles, train, Y))

    first, second = np.random.default_rng(SEED).integers(0, len(anime), (2, 20000))
    pair_cosines = (desc[first] * desc[second]).sum(1)[first != second]

    summary: dict[str, Any] = {
        "trained": n, "predicted": len(anime) - n,
        "sectors": k, "regions": offset, "between_share": round(float(between.mean()), 3),
    }
    if known.any():
        # As a viewer sees it: the map is fitted to the viewport, so both layouts are
        # fitted to the same box first and a shift or rescale of the whole map is free.
        def boxed(P: np.ndarray) -> np.ndarray:
            return (P - P.mean(0)) / (float(np.ptp(P, axis=0).max()) or 1.0)

        summary["median_movement"] = round(float(np.median(np.linalg.norm(boxed(Y[known]) - boxed(Y0[known]), axis=1))), 3)

    return {
        "stars": _stars(anime, X, Z, Y, sector, region, between, train),
        "groups": groups,
        "blob": pickle.dumps(m, protocol=5),
        # Synopsis similarity of random pairs, as percentiles.
        "pair_cosine_percentiles": [round(float(q), 4) for q in np.quantile(pair_cosines, np.linspace(0, 1, 101))],
        "summary": summary,
    }


def _group(level: str, number: int, parent: int | None, members: np.ndarray, reference: np.ndarray,
           anime: list[AnimeRow], profiles: list[dict[str, Any]], train: np.ndarray, Y: np.ndarray) -> dict[str, Any]:
    return {
        "level": level, "number": number, "parent": parent,
        "auto_name": auto_name(profiles, members, reference),
        "x": float(Y[members, 0].mean()), "y": float(Y[members, 1].mean()),
        "trained_members": sorted(anime[i].anime_id for i in members if train[i]),
    }


def place(blob: bytes, anime: list[AnimeRow], media: list[MediaRow]) -> list[dict[str, Any]]:
    """Predict stars for anime the fitted map has not seen, without moving anything."""
    m = pickle.loads(blob)
    profiles = _profiles(anime, media)
    desc = _unit(np.asarray([a.desc for a in anime], np.float32))
    X = _features(_raw_blocks(profiles, desc, m["stats"]), m["stats"])
    return _stars(anime, X, *_predict(m, X, _quality_era(profiles, m)), np.zeros(len(anime), bool))


def carry_names(previous: list[tuple[str, frozenset[int], str]],
                new: list[tuple[str, frozenset[int]]]) -> dict[int, str]:
    """Hand names onto a new fit, keyed by index into `new`. Groups are matched one to
    one, greedily by the Jaccard overlap of their trained members, within a level."""
    pairs = sorted(
        ((len(old & fresh) / len(old | fresh), i, j)
         for i, (level, old, _) in enumerate(previous)
         for j, (new_level, fresh) in enumerate(new)
         if level == new_level and old and fresh),
        reverse=True,
    )
    used_old: set[int] = set()
    out: dict[int, str] = {}
    for overlap, i, j in pairs:
        if overlap < NAME_FLOOR:
            break
        if i in used_old or j in out:
            continue
        used_old.add(i)
        out[j] = previous[i][2]
    return out


def auto_name(profiles: list[dict[str, Any]], members: np.ndarray, reference: np.ndarray) -> str:
    """The members' distinguishing values against a reference population — the catalogue
    for a sector, its sector for a region."""
    def shares(idx: np.ndarray, key: str) -> dict[str, float]:
        counts: Counter[str] = Counter()
        for i in idx:
            value = profiles[i][key]
            counts.update(value if isinstance(value, (list, set)) else [value] if value else [])
        return {k: c / len(idx) for k, c in counts.items()}

    parts = []
    ts, tr = shares(members, "majority_tags"), shares(reference, "majority_tags")
    picks = sorted(
        ((s * np.log(s / max(tr.get(t, 0), 1e-3)), t) for t, s in ts.items()
         if s >= 0.45 and s / max(tr.get(t, 0), 1e-3) >= 1.6),
        reverse=True,
    )
    parts += [t for _, t in picks[:3]]
    for key, floor, lift in (("top_source", 0.55, 1.4), ("studios", 0.3, 2.0)):
        ms, rs = shares(members, key), shares(reference, key)
        top = max(ms, key=ms.__getitem__) if ms else None
        if top and ms[top] >= floor and ms[top] / max(rs.get(top, 0), 1e-3) >= lift:
            parts.append(top)

    def median(idx: np.ndarray, key: str) -> float:
        values = [profiles[i][key] for i in idx if profiles[i][key] is not None]
        return float(np.median(values)) if values else float("nan")

    sc_m, sc_r = median(members, "score"), median(reference, "score")
    if sc_m - sc_r >= 0.35:
        parts.append(f"acclaimed ({sc_m:.1f})")
    elif sc_r - sc_m >= 0.35:
        parts.append(f"low-rated ({sc_m:.1f})")
    y_m, y_r = median(members, "year"), median(reference, "year")
    if y_r - y_m >= 6:
        parts.append(f"classic (~{int(y_m)})")
    elif y_m - y_r >= 2:
        parts.append(f"recent (~{int(y_m)})")
    return " · ".join(parts) or "mixed"
