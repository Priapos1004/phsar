"""Unit tests for the two-pass relation classifier.

Pure-function tests — no DB, no asyncio. Fixtures shape the (nodes,
edges) graph that pass 1 of the scraper would produce, then assert the
classifier's per-mal_id labels.
"""

from app.models.media import RelationType
from app.services.relation_classifier import (
    SUBSTANCE_MIN_EPISODES,
    SUBSTANCE_MIN_MOVIE_DURATION_S,
    SUBSTANCE_MIN_TV_DURATION_S,
    classify_anime_relations,
)


def _tv(episodes: int = 12, duration_s: int = 1440, aired: str = "2000-01-01", scored_by: int = 10_000):
    return {
        "media_type": "TV",
        "aired_from": aired,
        "episodes": episodes,
        "duration_seconds": duration_s,
        "scored_by": scored_by,
    }


def _movie(duration_s: int = 5400, aired: str = "2007-01-01"):
    return {
        "media_type": "Movie",
        "aired_from": aired,
        "episodes": 1,
        "duration_seconds": duration_s,
        "scored_by": 1_000,
    }


def _ona(episodes: int = 12, duration_s: int = 1440, aired: str = "2018-01-01"):
    return {
        "media_type": "ONA",
        "aired_from": aired,
        "episodes": episodes,
        "duration_seconds": duration_s,
        "scored_by": 1_000,
    }


def _special(duration_s: int = 600, aired: str = "2010-01-01"):
    return {
        "media_type": "Special",
        "aired_from": aired,
        "episodes": 1,
        "duration_seconds": duration_s,
        "scored_by": 100,
    }


# --- Evangelion ---------------------------------------------------------

def test_evangelion_tv_anchors_movies_are_alternative_version():
    # mal=30 Original TV; mal=2759..2762 Rebuild Movies 1-4;
    # mal=32 Death & Rebirth recap; mal=33 End of Evangelion.
    nodes = {
        30: _tv(episodes=26, duration_s=1440, aired="1995-10-04"),
        2759: _movie(duration_s=5400, aired="2007-09-01"),
        2760: _movie(duration_s=6480, aired="2009-06-27"),
        2761: _movie(duration_s=6480, aired="2012-11-17"),
        2762: _movie(duration_s=9000, aired="2021-03-08"),
        32: _movie(duration_s=4980, aired="1997-03-15"),
        33: _movie(duration_s=5520, aired="1997-07-19"),
    }
    edges = [
        (30, 2759, "alternative_version"),
        (2759, 2760, "sequel"),
        (2760, 2761, "sequel"),
        (2761, 2762, "sequel"),
        (30, 32, "side_story"),
        (30, 33, "side_story"),
    ]
    out = classify_anime_relations(nodes, edges)
    assert out[30] == "main"
    assert out[2759] == "alternative_version"
    assert out[2760] == "alternative_version"
    assert out[2761] == "alternative_version"
    assert out[2762] == "alternative_version"
    assert out[32] == "side_story"
    assert out[33] == "side_story"


# --- Overlord (in-graph weak mains) -------------------------------------

def test_overlord_in_graph_weak_mains_become_side_story():
    # Real-data shape: S1-S4 are TV mains; Pleiades (13min, 2 eps) and
    # Manner Movie (60s) are short and reach S1 via non-sequel edges.
    nodes = {
        29803: _tv(episodes=13, duration_s=1440, aired="2015-07-07"),
        32615: _tv(episodes=13, duration_s=1440, aired="2018-01-09"),
        37675: _tv(episodes=13, duration_s=1440, aired="2018-07-10"),
        48895: _tv(episodes=13, duration_s=1440, aired="2022-07-05"),
        36497: _movie(duration_s=780, aired="2018-01-09"),
        36683: _movie(duration_s=60, aired="2017-12-13"),
    }
    edges = [
        (29803, 32615, "sequel"),
        (32615, 37675, "sequel"),
        (37675, 48895, "sequel"),
        (29803, 36497, "side_story"),
        (29803, 36683, "other"),
    ]
    out = classify_anime_relations(nodes, edges)
    assert out[29803] == "main"
    assert out[32615] == "main"
    assert out[37675] == "main"
    assert out[48895] == "main"
    assert out[36497] == "side_story"
    assert out[36683] == "side_story"


def test_overlord_weak_sequel_demoted_by_substance_gate():
    # Hypothetical: MAL labels a 60s Movie as Sequel of S1. Two-pass
    # would put it in the main chain via the sequel edge; substance gate
    # demotes it to side_story.
    nodes = {
        100: _tv(episodes=13, duration_s=1440, aired="2015-01-01"),
        101: _movie(duration_s=60, aired="2017-01-01"),
    }
    edges = [(100, 101, "sequel")]
    out = classify_anime_relations(nodes, edges)
    assert out[100] == "main"
    assert out[101] == "side_story"


# --- Overlord standalone merge ------------------------------------------

def test_standalone_weak_movie_demoted_after_merge():
    # Simulates the post-merge consolidated graph: S1 + standalone
    # Manner Movie (which was its own anime, classified `main` because
    # it was the only node). After re-parenting, classifier runs over
    # the union and the weak movie loses its main status.
    nodes = {
        29803: _tv(episodes=13, duration_s=1440, aired="2015-07-07"),
        9999: _movie(duration_s=120, aired="2024-01-01"),
    }
    edges = [(29803, 9999, "other")]
    out = classify_anime_relations(nodes, edges)
    assert out[29803] == "main"
    assert out[9999] == "side_story"


# --- Donghua / ONA anchor -----------------------------------------------

def test_donghua_ona_anchors_when_no_tv_present():
    nodes = {
        200: _ona(episodes=26, duration_s=1320, aired="2018-06-09"),
        201: _ona(episodes=26, duration_s=1320, aired="2019-06-15"),
        202: _movie(duration_s=5400, aired="2020-08-01"),
    }
    edges = [
        (200, 201, "sequel"),
        (200, 202, "side_story"),
    ]
    out = classify_anime_relations(nodes, edges)
    assert out[200] == "main"
    assert out[201] == "main"
    assert out[202] == "side_story"


# --- Summary / crossover labels -----------------------------------------

def test_summary_edge_classifies_as_summary():
    nodes = {
        300: _tv(),
        301: _special(duration_s=600),
    }
    edges = [(300, 301, "summary")]
    out = classify_anime_relations(nodes, edges)
    assert out[301] == "summary"


def test_crossover_edge_classifies_as_crossover():
    nodes = {
        400: _tv(),
        401: _movie(),
    }
    edges = [(400, 401, "crossover")]
    out = classify_anime_relations(nodes, edges)
    assert out[401] == "crossover"


def test_summary_outranks_side_story_when_node_has_both_edges():
    nodes = {
        500: _tv(),
        501: _special(),
    }
    edges = [
        (500, 501, "side_story"),
        (500, 501, "summary"),
    ]
    out = classify_anime_relations(nodes, edges)
    assert out[501] == "summary"


# --- Anchor selection rules ---------------------------------------------

def test_tv_beats_movie_even_when_movie_aired_first():
    nodes = {
        600: _movie(duration_s=5400, aired="1990-01-01"),  # older Movie
        601: _tv(episodes=12, duration_s=1440, aired="2000-01-01"),  # newer TV
    }
    edges = [(600, 601, "alternative_version")]
    out = classify_anime_relations(nodes, edges)
    assert out[601] == "main"
    assert out[600] == "alternative_version"


def test_oldest_tv_wins_within_tier():
    nodes = {
        700: _tv(aired="2010-01-01"),
        701: _tv(aired="2005-01-01"),
        702: _tv(aired="2015-01-01"),
    }
    edges = [
        (700, 701, "sequel"),
        (701, 702, "sequel"),
    ]
    out = classify_anime_relations(nodes, edges)
    assert out == {700: "main", 701: "main", 702: "main"}


def test_scored_by_breaks_tier_aired_tie():
    nodes = {
        800: _tv(aired="2010-01-01", scored_by=100),
        801: _tv(aired="2010-01-01", scored_by=100_000),
    }
    edges = [(800, 801, "alternative_version")]
    out = classify_anime_relations(nodes, edges)
    assert out[801] == "main"
    assert out[800] == "alternative_version"


# --- Substance-gate fallback (no substance-passing node) -----------------

def test_anchor_falls_back_when_no_node_passes_substance():
    # Single Special, 5min, 1 ep. Fails substance but must still anchor
    # the anime row.
    nodes = {900: _special(duration_s=300)}
    edges: list[tuple[int, int, str]] = []
    out = classify_anime_relations(nodes, edges)
    assert out[900] == "main"


def test_anchor_fallback_picks_most_main_like_type():
    # Both fail substance. Tier order picks the Movie over the Special.
    nodes = {
        1000: _special(duration_s=300, aired="2010-01-01"),
        1001: _movie(duration_s=600, aired="2015-01-01"),
    }
    edges = [(1000, 1001, "side_story")]
    out = classify_anime_relations(nodes, edges)
    assert out[1001] == "main"
    assert out[1000] == "side_story"


# --- Edge cases ---------------------------------------------------------

def test_classifier_outputs_are_valid_relation_type_values():
    # Catches enum drift: if a future change introduces a new return
    # string without adding a matching RelationType member, the DB
    # column write would fail at runtime — this test fails first.
    nodes = {
        1: _tv(),
        2: _movie(),
        3: _special(),
        4: _movie(duration_s=60),
    }
    edges = [
        (1, 2, "alternative_version"),
        (1, 3, "summary"),
        (1, 4, "crossover"),
    ]
    out = classify_anime_relations(nodes, edges)
    valid = {rt.value for rt in RelationType}
    assert set(out.values()) <= valid


def test_classifier_ignores_dangling_edges():
    """Sidecars persist full MAL relation lists, including targets
    outside the current input set (so a future merge can surface
    bridge edges). The classifier must filter those defensively —
    without dropping them, the closure would visit non-existent
    mal_ids and substance demotion would KeyError on nodes[mal_id]."""
    nodes = {
        1: _tv(episodes=12, duration_s=1440, aired="2020-01-01"),
        2: _tv(episodes=12, duration_s=1440, aired="2021-01-01"),
    }
    edges = [
        (1, 2, "sequel"),
        (2, 999, "sequel"),  # dangling — 999 is not in nodes
        (888, 1, "prequel"),  # dangling — 888 is not in nodes
    ]
    out = classify_anime_relations(nodes, edges)
    assert out == {1: "main", 2: "main"}


def test_empty_graph_returns_empty_dict():
    assert classify_anime_relations({}, []) == {}


def test_single_node_is_main():
    nodes = {1100: _tv()}
    out = classify_anime_relations(nodes, [])
    assert out == {1100: "main"}


def test_disconnected_subgraph_defaults_to_side_story():
    nodes = {
        1200: _tv(),
        1201: _movie(),
    }
    edges: list[tuple[int, int, str]] = []
    out = classify_anime_relations(nodes, edges)
    assert out[1200] == "main"
    assert out[1201] == "side_story"


def test_currently_airing_tv_with_null_episodes_passes_substance():
    """Long-running TVs (Conan, Anpanman) have episodes=None because MAL
    has no terminal count. They must still pass substance — otherwise
    a sequel Movie / spin-off TV gets picked as anchor over the
    canonical original. TVSpecial keeps the strict episode requirement."""
    # Long-running TV anchor + a substance-passing Movie sibling.
    nodes = {
        1: _tv(episodes=12, duration_s=1440, aired="1996-01-08"),
        2: _movie(duration_s=4200, aired="2014-01-01"),
    }
    nodes[1]["episodes"] = None
    edges = [(1, 2, "alternative_version")]
    out = classify_anime_relations(nodes, edges)
    # TV with NULL episodes anchors over the substance-passing Movie.
    assert out[1] == "main"
    assert out[2] == "alternative_version"


def test_tvspecial_with_null_episodes_fails_substance():
    """TVSpecial is bounded by definition; NULL episodes means MAL data
    is incomplete, not "ongoing." Stay strict."""
    nodes = {
        1: {"media_type": "TVSpecial", "aired_from": "2020-01-01",
            "episodes": None, "duration_seconds": 1440, "scored_by": 100},
        2: _tv(episodes=26, duration_s=1440, aired="2021-01-01"),
    }
    edges = [(1, 2, "sequel")]
    out = classify_anime_relations(nodes, edges)
    # The substance-passing TV anchors; TVSpecial with NULL eps doesn't.
    assert out[2] == "main"


def test_substance_thresholds_match_constants():
    tv_pass = {1300: _tv(episodes=SUBSTANCE_MIN_EPISODES, duration_s=SUBSTANCE_MIN_TV_DURATION_S)}
    tv_below_eps = {1301: _tv(episodes=SUBSTANCE_MIN_EPISODES - 1, duration_s=SUBSTANCE_MIN_TV_DURATION_S)}
    tv_below_dur = {1302: _tv(episodes=SUBSTANCE_MIN_EPISODES, duration_s=SUBSTANCE_MIN_TV_DURATION_S - 1)}
    movie_pass = {1303: _movie(duration_s=SUBSTANCE_MIN_MOVIE_DURATION_S)}
    movie_below = {1304: _movie(duration_s=SUBSTANCE_MIN_MOVIE_DURATION_S - 1)}

    # The substance gate's effect is observable only when there's a
    # competing substance-passing node; otherwise the fallback picks
    # the only available anchor regardless. Pair each weak node with a
    # strong TV so the fallback doesn't fire.
    strong = {1: _tv(episodes=26, duration_s=1440, aired="2000-01-01")}
    for weak in (tv_pass, tv_below_eps, tv_below_dur, movie_pass, movie_below):
        nodes = {**strong, **weak}
        weak_id = next(iter(weak))
        edges = [(1, weak_id, "sequel")]
        out = classify_anime_relations(nodes, edges)
        assert out[1] == "main"
        # Weak gets demoted iff it doesn't pass substance.
        if weak_id in (1300, 1303):  # the two passing fixtures
            assert out[weak_id] == "main", f"{weak_id} should pass substance"
        else:
            assert out[weak_id] == "side_story", f"{weak_id} should fail substance"
