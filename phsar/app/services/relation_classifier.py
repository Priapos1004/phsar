"""Two-pass relation classifier for anime media graphs.

Pass 1 (in `jikan_scraper.py`) captures relation EDGES during BFS instead
of classifying nodes inline. Pass 2 (this module) picks a canonical
anchor, builds the main chain via sequel/prequel transitive closure,
classifies alt-version branches, then defaults the rest to side_story.

Path-dependent classification was the root cause of the Evangelion
umbrella anchoring on Rebuild Movie 1 (see Issue 2b in
compound-docs/2026-05-11-jikan-scraper-quirks.md). With nodes + edges
known up front, anchor choice no longer depends on which media the user
searched for.

The function is pure and DB-less so it can be exercised at scrape time,
at merge time over a consolidated graph, and at backfill time over the
existing catalog without changing implementation.
"""

from collections import defaultdict, deque
from typing import TypedDict


class ClassifierNode(TypedDict):
    media_type: str | None
    aired_from: str | None
    episodes: int | None
    duration_seconds: int | None
    scored_by: int


class DisjointFranchise(TypedDict):
    member_mal_ids: list[int]
    substance_member_mal_ids: list[int]
    suggested_anchor_mal_id: int
    # Edges (a, b, rel) where one endpoint is in `anchored` (main_chain ∪
    # alt_chain) and the other is in the cluster — the MAL relations that
    # caused the BFS to absorb this cluster under the parent anime.
    # Used by split-execution to surface "why was this bundled" to admin
    # and by the Conan-exclusion heuristic in find_disjoint_franchises.
    bridge_edges: list[tuple[int, int, str]]


SUBSTANCE_MIN_EPISODES = 8
SUBSTANCE_MIN_TV_DURATION_S = 900    # 15 min
SUBSTANCE_MIN_MOVIE_DURATION_S = 1800  # 30 min

_TV_LIKE_TYPES = frozenset({"tv", "ona", "tvspecial"})
_MOVIE_TYPES = frozenset({"movie"})

# Fallback tier 4 covers OVA / Special / anything else that passed
# substance but isn't canonical-shaped.
_ANCHOR_TIER = {
    "tv": 1,
    "ona": 2,
    "movie": 3,
}
_ANCHOR_TIER_FALLBACK = 4

_MAIN_CHAIN_EDGES = frozenset({"sequel", "prequel"})
_ALT_CHAIN_EDGES = frozenset({"sequel", "prequel", "alternative_version"})


def _normalize_media_type(media_type: str | None) -> str:
    if not media_type:
        return ""
    return media_type.replace(" ", "").lower()


def passes_substance(node: ClassifierNode) -> bool:
    media_type = _normalize_media_type(node.get("media_type"))
    duration = node.get("duration_seconds")
    episodes = node.get("episodes")
    if media_type in _TV_LIKE_TYPES:
        if duration is None or duration < SUBSTANCE_MIN_TV_DURATION_S:
            return False
        # TV and ONA: NULL episodes is normal for currently-airing /
        # long-running shows that have no terminal count (Conan,
        # Anpanman, mid-arc donghua). For TVSpecial — bounded by
        # definition — require an explicit count.
        if media_type == "tvspecial":
            return episodes is not None and episodes >= SUBSTANCE_MIN_EPISODES
        return episodes is None or episodes >= SUBSTANCE_MIN_EPISODES
    if media_type in _MOVIE_TYPES:
        if duration is None:
            return False
        return duration >= SUBSTANCE_MIN_MOVIE_DURATION_S
    return False


def anchor_tier(media_type: str | None) -> int:
    """Public tier rank for a MAL media_type string. Lower = more canonical
    (TV=1 > ONA=2 > Movie=3 > other=4). Normalizes whitespace + case so
    callers can pass raw MAL `type` fields ("TV Special", "Movie") without
    pre-processing. Used by the classifier's anchor selection AND the
    scraper's pre-BFS root sort — keeping them in one helper guarantees
    the two paths agree on what "more canonical" means.
    """
    return _ANCHOR_TIER.get(_normalize_media_type(media_type), _ANCHOR_TIER_FALLBACK)


def _anchor_sort_key(mal_id: int, node: ClassifierNode) -> tuple:
    tier = anchor_tier(node.get("media_type"))
    aired = node.get("aired_from")
    scored_by = node.get("scored_by") or 0
    # Bucket nulls last within a tier so a typed-but-undated entry never
    # beats one with a real date. Within non-nulls, oldest wins.
    if aired is None:
        aired_sort = (1, "")
    else:
        aired_sort = (0, aired)
    return (tier, aired_sort, -scored_by, mal_id)


def _pick_anchor(nodes: dict[int, ClassifierNode]) -> int:
    """Internal: return the mal_id the classifier would anchor on for
    this graph. `classify_anime_relations` returns this in its tuple, so
    external callers don't need it standalone."""
    substance_passing = {m: n for m, n in nodes.items() if passes_substance(n)}
    # Fallback covers donghua / orphan-side-story / standalone-weak-anime
    # cases where nothing passes substance — pick the most main-like
    # node anyway so the anime row has a `main`.
    candidates = substance_passing or nodes
    return min(candidates.items(), key=lambda kv: _anchor_sort_key(kv[0], kv[1]))[0]


def _build_adjacency(
    edges: list[tuple[int, int, str]],
    valid_ids: set[int],
) -> dict[int, list[tuple[int, str]]]:
    # Undirected adjacency: MAL relations are reciprocal across the pair
    # (A → Sequel → B implies B → Prequel → A) so either direction
    # counts for classifier traversal.
    #
    # Edges with at least one endpoint outside `valid_ids` are dropped
    # defensively. Sidecars persist all observed MAL edges including
    # ones pointing to media outside this anime's graph (so a future
    # merge surfaces previously-dangling bridge edges) — at classify
    # time we still want to traverse only edges that connect nodes the
    # caller passed in.
    adj: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for a, b, rel in edges:
        if a not in valid_ids or b not in valid_ids:
            continue
        adj[a].append((b, rel))
        adj[b].append((a, rel))
    return adj


def _closure(
    starts: set[int],
    adj: dict[int, list[tuple[int, str]]],
    allowed_rels: frozenset[str],
    excluded: set[int],
) -> set[int]:
    visited: set[int] = set(starts)
    queue: deque[int] = deque(starts)
    while queue:
        cur = queue.popleft()
        for neighbor, rel in adj.get(cur, []):
            if neighbor in visited or neighbor in excluded:
                continue
            if rel not in allowed_rels:
                continue
            visited.add(neighbor)
            queue.append(neighbor)
    return visited


def outgoing_edges(
    edges: list[tuple[int, int, str]], source_mal_id: int,
) -> list[tuple[int, str]]:
    """Project per-anime edges to the per-media outgoing list persisted
    on MediaRelationEdges. `[target_mal_id, rel]` pairs match the JSONB
    column shape the merge/preview/backfill paths read back."""
    return [(target, rel) for src, target, rel in edges if src == source_mal_id]


def media_to_classifier_node(media) -> ClassifierNode:
    """Project a `Media` ORM row into the ClassifierNode shape. Co-
    located with `build_classifier_nodes` (the scraper-dict equivalent)
    so a future ClassifierNode field addition surfaces both projections.
    """
    return {
        "media_type": media.media_type.value,
        "aired_from": media.aired_from.isoformat() if media.aired_from else None,
        "episodes": media.episodes,
        "duration_seconds": media.duration_seconds,
        "scored_by": media.scored_by or 0,
    }


def build_classifier_nodes(
    graph: dict[int, dict], all_info: dict[int, dict],
) -> dict[int, ClassifierNode]:
    """Project per-anime `all_info` into the ClassifierNode shape for
    every mal_id in `graph`. Skips mal_ids absent from all_info so a
    partially-extracted graph doesn't crash the classifier."""
    return {
        mal_id: {
            "media_type": all_info[mal_id].get("media_type"),
            "aired_from": all_info[mal_id].get("aired_from"),
            "episodes": all_info[mal_id].get("episodes"),
            "duration_seconds": all_info[mal_id].get("duration_seconds"),
            "scored_by": all_info[mal_id].get("scored_by") or 0,
        }
        for mal_id in graph
        if mal_id in all_info
    }


def classify_and_stamp(
    graph: dict[int, dict],
    edges: list[tuple[int, int, str]],
    all_info: dict[int, dict],
) -> dict[int, str]:
    """Classify a per-anime graph and stamp `relation_type` on each
    graph entry in place. Returns the classifications so callers can
    look up the anchor without re-iterating."""
    nodes = build_classifier_nodes(graph, all_info)
    classifications, _ = classify_anime_relations(nodes, edges)
    for mal_id, relation_type in classifications.items():
        graph[mal_id]["relation_type"] = relation_type
    return classifications


def classify_anime_relations(
    nodes: dict[int, ClassifierNode],
    edges: list[tuple[int, int, str]],
) -> tuple[dict[int, str], int | None]:
    """Classify every node in `nodes` as one of: main, alternative_version,
    side_story, summary, crossover. Returns `(classifications, anchor)`
    where `anchor` is the mal_id picked by the substance-gate + tier
    sort (or `None` for empty input). Callers that need the anchor
    don't have to call `_pick_anchor` separately.

    `nodes` maps `mal_id` to a node dict (see ClassifierNode TypedDict).
    `edges` is a list of (a, b, normalized_relation) tuples where
    `normalized_relation` matches `jikan_scraper.normalize_relation`
    output (lowercased, spaces → underscores).
    """
    if not nodes:
        return {}, None

    anchor = _pick_anchor(nodes)
    adj = _build_adjacency(edges, valid_ids=set(nodes.keys()))

    main_chain = _closure({anchor}, adj, _MAIN_CHAIN_EDGES, set())

    # Alt-chain seeds: nodes adjacent to main chain via an alt-version edge.
    # Closure expands via sequel/prequel/alt-version so a chain of sequel'd
    # alt-versions (Rebuild Movie 1 → 2 → 3 → 4) all inherit the label.
    alt_seeds = {
        neighbor
        for main_node in main_chain
        for neighbor, rel in adj.get(main_node, [])
        if rel == "alternative_version" and neighbor not in main_chain
    }
    alt_chain = _closure(alt_seeds, adj, _ALT_CHAIN_EDGES, main_chain)

    anchored = main_chain | alt_chain
    classifications: dict[int, str] = {}
    for mal_id in nodes:
        if mal_id in main_chain:
            classifications[mal_id] = "main"
            continue
        if mal_id in alt_chain:
            classifications[mal_id] = "alternative_version"
            continue
        edge_types = {rel for n, rel in adj.get(mal_id, []) if n in anchored}
        if "summary" in edge_types:
            classifications[mal_id] = "summary"
        elif "crossover" in edge_types:
            classifications[mal_id] = "crossover"
        else:
            classifications[mal_id] = "side_story"

    # Substance demotion: weak-main media inside the main chain (except the
    # anchor) drops to side_story. Load-bearing at merge time when a
    # standalone weak-anime (e.g. the Overlord 2024 standalone Manner Movie)
    # gets absorbed and would otherwise inherit `main`.
    for mal_id in main_chain:
        if mal_id == anchor:
            continue
        if not passes_substance(nodes[mal_id]):
            classifications[mal_id] = "side_story"

    return classifications, anchor


def would_be_dropped_as_weak_anchor(
    nodes: dict[int, ClassifierNode],
    anchor: int | None,
    seed_mal_id: int | None,
    cross_link_mal_ids: set[int],
) -> bool:
    """Mirror of the weak-anchor-skip branch in
    `search_service.search_mal_api`. Returns True when the (nodes, edges)
    graph would be silently dropped at save time: anchor fails substance
    AND there's no attach target (single cross-link) AND no seed.

    Used by `jikan_scraper.search_title` to detect this case BEFORE
    appending the graph to `relations`, so the visited_ids claims for
    those mal_ids can be rolled back and subsequent roots' BFS can
    include them. Keeping the predicate in one place couples the
    rollback decision to the actual save-time decision so future edits
    to one site can't silently drift from the other — same drift class
    as the v0.14.0 `_normalize_relation` bug (compound-doc reference).
    """
    if anchor is None:
        return False
    if passes_substance(nodes[anchor]):
        return False
    if seed_mal_id is not None:
        return False
    if len(cross_link_mal_ids) == 1:
        return False
    return True


# Edge labels that, when present on the bridge between an orphan cluster
# and the anchored set, mean MAL is explicitly declaring the cluster a
# child story of the parent franchise (not a sibling franchise). The
# Conan-style exception (movie-only side-story chains attached via
# parent_story/summary) uses these to skip flagging legitimate side-story
# trees as contamination. `side_story` is intentionally absent — MAL also
# uses it for sibling sub-franchises like Toaru Index → Railgun, so it's
# not a reliable signal of child-vs-sibling on its own.
_CHILD_STORY_BRIDGE_RELS = frozenset({"parent_story", "summary"})


def find_disjoint_franchises(
    nodes: dict[int, ClassifierNode],
    edges: list[tuple[int, int, str]],
    anchor: int | None,
) -> list[DisjointFranchise]:
    """Find substance-passing main-chain clusters under one anime row
    that the classifier didn't absorb into the anchor's main or alt
    chain — these are sibling franchises bundled together via MAL's
    promiscuous `side_story` / `spin-off` / `other` labeling (BNHA→
    Vigilante, Toaru Index→Railgun, Pretty Rhythm→PriPara/King of Prism).

    Pure function: same `(nodes, edges)` shape as `classify_anime_relations`,
    no DB or seed knowledge — result is identical at scrape, merge, and
    backfill time. `anchor` should be the classifier's anchor (the second
    return value of `classify_anime_relations`); pass `None` for empty
    graphs and the function returns `[]` immediately.

    Returns one `DisjointFranchise` per detected cluster. Empty list when
    the graph is clean — the common case.

    Detection algorithm (matches phsar/scripts/audit_cross_franchise.py):
      1. Compute the anchor's main_chain (sequel/prequel closure) and
         alt_chain (alternative_version seeds + sequel/prequel/alt-version
         closure). Union = the `anchored` set.
      2. Substance-passing nodes outside `anchored` are orphans.
      3. Cluster orphans by their own main-chain reachability. A cluster
         with ≥2 substance-passing members signals a disjoint franchise
         main chain — the Overlord+Eminence shape.

    Conan-exception (must-NOT-flag): if a cluster contains only Movies AND
    at least one bridge edge to the anchored set is labeled `parent_story`
    or `summary`, MAL is asserting "this is a child story" and we trust
    it. Conan Movie-N + summary-of-Movie-N pairs trip the disjoint-cluster
    detector via sequel chains between movies, but they're legitimate
    side-stories; the exception keeps them quiet. Vigilante (TV-tier) and
    Railgun (TV-tier) are unaffected — they're not movie-only.
    """
    if not nodes or anchor is None:
        return []

    adj = _build_adjacency(edges, valid_ids=set(nodes.keys()))
    main_chain = _closure({anchor}, adj, _MAIN_CHAIN_EDGES, set())
    alt_seeds = {
        neighbor
        for main_node in main_chain
        for neighbor, rel in adj.get(main_node, [])
        if rel == "alternative_version" and neighbor not in main_chain
    }
    alt_chain = _closure(alt_seeds, adj, _ALT_CHAIN_EDGES, main_chain)
    anchored = main_chain | alt_chain

    substance_passing = {
        mal_id for mal_id, node in nodes.items() if passes_substance(node)
    }
    orphans = substance_passing - anchored

    franchises: list[DisjointFranchise] = []
    visited: set[int] = set()
    for orphan in sorted(orphans):
        if orphan in visited:
            continue
        # `excluded=anchored` is technically redundant (anchored is already
        # closed under main-chain edges so an orphan's closure can't reach
        # it), but stating the disjoint-cluster invariant in the call is
        # cheaper than commenting it for future readers.
        cluster = _closure({orphan}, adj, _MAIN_CHAIN_EDGES, anchored)
        visited |= cluster
        substance_in_cluster = cluster & substance_passing
        if len(substance_in_cluster) < 2:
            continue

        bridge_edges = [
            (a, b, rel) for a, b, rel in edges
            if (a in anchored and b in cluster) or (a in cluster and b in anchored)
        ]

        if _is_legitimate_side_story_chain(cluster, nodes, bridge_edges):
            continue

        cluster_nodes = {mid: nodes[mid] for mid in cluster}
        suggested_anchor = _pick_anchor(cluster_nodes)

        franchises.append({
            "member_mal_ids": sorted(cluster),
            "substance_member_mal_ids": sorted(substance_in_cluster),
            "suggested_anchor_mal_id": suggested_anchor,
            "bridge_edges": bridge_edges,
        })

    return franchises


def _is_legitimate_side_story_chain(
    cluster: set[int],
    nodes: dict[int, ClassifierNode],
    bridge_edges: list[tuple[int, int, str]],
) -> bool:
    # Conan exception: a movie-only cluster reached via at least one
    # `parent_story` or `summary` edge is MAL asserting "child story of
    # the parent franchise" — not a sibling franchise. Mononoke 2024
    # movie trilogy reached via dropped `alternative_setting` lands here
    # with empty parent_story bridges → falls through, gets flagged.
    all_movies = all(
        _normalize_media_type(nodes[mal_id]["media_type"]) in _MOVIE_TYPES
        for mal_id in cluster
    )
    if not all_movies:
        return False
    return any(rel in _CHILD_STORY_BRIDGE_RELS for _, _, rel in bridge_edges)
