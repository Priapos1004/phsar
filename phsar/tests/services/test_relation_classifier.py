"""Unit tests for the two-pass relation classifier.

Pure-function tests — no DB, no asyncio. Fixtures shape the (nodes,
edges) graph that pass 1 of the scraper would produce, then assert the
classifier's per-mal_id labels.
"""

from app.models.media import RelationType
from app.services.relation_classifier import (
    FEATURE_LENGTH_ONA_MIN_DURATION_S,
    SUBSTANCE_MIN_EPISODES,
    SUBSTANCE_MIN_MOVIE_DURATION_S,
    SUBSTANCE_MIN_TV_DURATION_S,
    SUBSTANCE_POPULAR_WAIVER_SCORED_BY,
    classify_anime_relations,
    find_disjoint_franchises,
    passes_feature_length_ona_waiver,
    passes_popularity_waiver,
    passes_substance,
    would_be_dropped_as_weak_anchor,
)


def _tv(episodes: int | None = 12, duration_s: int | None = 1440,
        aired: str | None = "2000-01-01",
        scored_by: int = 10_000, airing_status: str = "Finished Airing"):
    return {
        "media_type": "TV",
        "aired_from": aired,
        "episodes": episodes,
        "duration_seconds": duration_s,
        "scored_by": scored_by,
        "airing_status": airing_status,
    }


def _movie(duration_s: int = 5400, aired: str = "2007-01-01",
           airing_status: str = "Finished Airing"):
    return {
        "media_type": "Movie",
        "aired_from": aired,
        "episodes": 1,
        "duration_seconds": duration_s,
        "scored_by": 1_000,
        "airing_status": airing_status,
    }


def _ona(episodes: int = 12, duration_s: int = 1440, aired: str = "2018-01-01",
         airing_status: str = "Finished Airing"):
    return {
        "media_type": "ONA",
        "aired_from": aired,
        "episodes": episodes,
        "duration_seconds": duration_s,
        "scored_by": 1_000,
        "airing_status": airing_status,
    }


def _special(duration_s: int = 600, aired: str = "2010-01-01",
             airing_status: str = "Finished Airing"):
    return {
        "media_type": "Special",
        "aired_from": aired,
        "episodes": 1,
        "duration_seconds": duration_s,
        "scored_by": 100,
        "airing_status": airing_status,
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
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
    assert out[301] == "summary"


def test_crossover_edge_classifies_as_crossover():
    nodes = {
        400: _tv(),
        401: _movie(),
    }
    edges = [(400, 401, "crossover")]
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
    assert out[501] == "summary"


# --- Anchor selection rules ---------------------------------------------

def test_tv_beats_movie_even_when_movie_aired_first():
    nodes = {
        600: _movie(duration_s=5400, aired="1990-01-01"),  # older Movie
        601: _tv(episodes=12, duration_s=1440, aired="2000-01-01"),  # newer TV
    }
    edges = [(600, 601, "alternative_version")]
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
    assert out == {700: "main", 701: "main", 702: "main"}


def test_scored_by_breaks_tier_aired_tie():
    nodes = {
        800: _tv(aired="2010-01-01", scored_by=100),
        801: _tv(aired="2010-01-01", scored_by=100_000),
    }
    edges = [(800, 801, "alternative_version")]
    out, _ = classify_anime_relations(nodes, edges)
    assert out[801] == "main"
    assert out[800] == "alternative_version"


# --- Substance-gate fallback (no substance-passing node) -----------------

def test_anchor_falls_back_when_no_node_passes_substance():
    # Single Special, 5min, 1 ep. Fails substance but must still anchor
    # the anime row.
    nodes = {900: _special(duration_s=300)}
    edges: list[tuple[int, int, str]] = []
    out, _ = classify_anime_relations(nodes, edges)
    assert out[900] == "main"


def test_anchor_fallback_picks_most_main_like_type():
    # Both fail substance. Tier order picks the Movie over the Special.
    nodes = {
        1000: _special(duration_s=300, aired="2010-01-01"),
        1001: _movie(duration_s=600, aired="2015-01-01"),
    }
    edges = [(1000, 1001, "side_story")]
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
    assert out == {1: "main", 2: "main"}


def test_empty_graph_returns_empty_dict():
    classifications, anchor = classify_anime_relations({}, [])
    assert classifications == {}
    assert anchor is None


def test_single_node_is_main():
    nodes = {1100: _tv()}
    out, anchor = classify_anime_relations(nodes, [])
    assert out == {1100: "main"}
    assert anchor == 1100


def test_disconnected_subgraph_defaults_to_side_story():
    nodes = {
        1200: _tv(),
        1201: _movie(),
    }
    edges: list[tuple[int, int, str]] = []
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
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
    out, _ = classify_anime_relations(nodes, edges)
    # The substance-passing TV anchors; TVSpecial with NULL eps doesn't.
    assert out[2] == "main"


def test_not_yet_aired_sequel_with_null_metadata_stays_main():
    """Hell Mode repro: an announced S2 has episodes=None AND
    duration=None (MAL hasn't published runtime months before air). It's
    reached via the sequel edge into the main chain and must NOT be
    demoted to side_story on that not-yet-published absence."""
    nodes = {
        60460: _tv(episodes=12, duration_s=1380, aired="2026-01-10"),
        63817: _tv(episodes=None, duration_s=None, aired="2026-07-01",
                   airing_status="Not yet aired"),
    }
    edges = [(60460, 63817, "sequel"), (63817, 60460, "prequel")]
    out, _ = classify_anime_relations(nodes, edges)
    assert out[60460] == "main"
    assert out[63817] == "main"


def test_finished_airing_sequel_with_null_duration_demoted():
    """A *finished* entry with NULL duration is a genuine data anomaly,
    not pending metadata — keep demoting it."""
    nodes = {
        1: _tv(episodes=12, duration_s=1440, aired="2000-01-01"),
        2: _tv(episodes=None, duration_s=None, aired="2001-01-01",
               airing_status="Finished Airing"),
    }
    edges = [(1, 2, "sequel")]
    out, _ = classify_anime_relations(nodes, edges)
    assert out[1] == "main"
    assert out[2] == "side_story"


def test_not_yet_aired_short_pv_still_excluded():
    """A populated-but-short duration fails regardless of airing status —
    an announced 60s PV-as-TV must not provisionally pass."""
    nodes = {
        1: _tv(episodes=12, duration_s=1440, aired="2000-01-01"),
        2: _tv(episodes=None, duration_s=60, aired="2026-01-01",
               airing_status="Not yet aired"),
    }
    edges = [(1, 2, "sequel")]
    out, _ = classify_anime_relations(nodes, edges)
    assert out[1] == "main"
    assert out[2] == "side_story"


def test_currently_airing_null_duration_does_not_steal_anchor():
    """Locks the not-yet-aired-ONLY decision (the Fei Ren Zai shape): a
    currently-airing ONA with NULL duration must NOT provisionally pass,
    so it can't out-tier the Movie anchor and steal the umbrella onto a
    mid-franchise part. Currently Airing is deliberately excluded from the
    pending exemption — an airing show normally has a published duration."""
    nodes = {
        62260: _movie(duration_s=6420, aired="2025-08-16"),
        63788: _ona(episodes=None, duration_s=None, aired="2026-05-05",
                    airing_status="Currently Airing"),
    }
    edges = [(62260, 63788, "sequel"), (63788, 62260, "prequel")]
    out, anchor = classify_anime_relations(nodes, edges)
    assert anchor == 62260
    assert out[62260] == "main"
    assert out[63788] == "side_story"


def test_not_yet_aired_does_not_anchor_short_form_franchise():
    """Hyakushou Kizoku shape: every aired season is short-form (240s),
    failing the duration gate, so none pass substance. A not-yet-aired
    next season (NULL duration) gets a provisional pass — but it must NOT
    become the umbrella anchor (you can't anchor on an unaired entry).
    Anchor stays the oldest aired TV; the not-yet-aired season is still
    promoted to main (in the chain), just not the anchor."""
    nodes = {
        1: _tv(episodes=12, duration_s=240, aired="2023-07-07"),
        2: _tv(episodes=12, duration_s=240, aired="2024-10-04"),
        3: _tv(episodes=None, duration_s=None, aired=None,
               airing_status="Not yet aired"),
    }
    edges = [(1, 2, "sequel"), (2, 3, "sequel"), (3, 2, "prequel"), (2, 1, "prequel")]
    out, anchor = classify_anime_relations(nodes, edges)
    assert anchor == 1  # the oldest aired TV, NOT the unaired season 3
    assert out[1] == "main"


def test_single_not_yet_aired_media_is_main():
    """A brand-new franchise whose only entry hasn't aired yet (NULL
    duration/episodes) must still classify as main — the pending node is
    anchor-ineligible, but `_pick_anchor` falls back to all nodes when
    nothing is eligible, so the lone node anchors and stays main."""
    nodes = {1: _tv(episodes=None, duration_s=None, aired=None,
                    airing_status="Not yet aired")}
    out, anchor = classify_anime_relations(nodes, [])
    assert anchor == 1
    assert out[1] == "main"


def test_short_duration_franchise_keeps_seasons_main():
    """Opantsu shape: every aired entry is short-form (240s, 6 eps), so
    NEITHER substance floor discriminates — both relax, and the sequel
    chain stays main instead of all-but-anchor collapsing to side_story."""
    nodes = {
        1: _tv(episodes=6, duration_s=240, aired="2020-01-01"),
        2: _tv(episodes=6, duration_s=240, aired="2021-01-01"),
        3: _tv(episodes=6, duration_s=240, aired="2022-01-01"),
    }
    edges = [(1, 2, "sequel"), (2, 3, "sequel"), (3, 2, "prequel"), (2, 1, "prequel")]
    out, anchor = classify_anime_relations(nodes, edges)
    assert anchor == 1
    assert out[1] == "main" and out[2] == "main" and out[3] == "main"


def test_short_duration_franchise_episode_floor_still_demotes():
    """The key per-constraint case: short-DURATION franchise (nothing ≥600s →
    duration floor relaxed) but the 12-ep seasons satisfy the EPISODE floor,
    so it stays active — a 5-ep sequel in the chain still demotes to side_story
    instead of riding along as main."""
    nodes = {
        1: _tv(episodes=12, duration_s=240, aired="2020-01-01"),
        2: _tv(episodes=12, duration_s=240, aired="2021-01-01"),
        3: _tv(episodes=5, duration_s=240, aired="2022-01-01"),
    }
    edges = [(1, 2, "sequel"), (2, 3, "sequel"), (3, 2, "prequel"), (2, 1, "prequel")]
    out, _ = classify_anime_relations(nodes, edges)
    assert out[1] == "main" and out[2] == "main"
    assert out[3] == "side_story"


def test_mixed_duration_franchise_still_demotes_short_sequel():
    """When a real full-length season exists, both floors are satisfied →
    nothing relaxes → a short-form sequel demotes exactly as before (no
    regression to the demotion's load-bearing behavior)."""
    nodes = {
        1: _tv(episodes=12, duration_s=1440, aired="2020-01-01"),
        2: _tv(episodes=6, duration_s=240, aired="2021-01-01"),
    }
    edges = [(1, 2, "sequel"), (2, 1, "prequel")]
    out, _ = classify_anime_relations(nodes, edges)
    assert out[1] == "main"
    assert out[2] == "side_story"


def test_not_yet_aired_sequel_movie_with_null_duration_stays_main():
    """Movie symmetry: an announced sequel movie with no runtime yet
    stays in the main chain instead of being demoted."""
    nodes = {
        1: _movie(duration_s=5400, aired="2007-01-01"),
        2: _movie(duration_s=None, aired="2026-09-11",
                  airing_status="Not yet aired"),
    }
    edges = [(1, 2, "sequel"), (2, 1, "prequel")]
    out, _ = classify_anime_relations(nodes, edges)
    assert out[1] == "main"
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
        out, _ = classify_anime_relations(nodes, edges)
        assert out[1] == "main"
        # Weak gets demoted iff it doesn't pass substance.
        if weak_id in (1300, 1303):  # the two passing fixtures
            assert out[weak_id] == "main", f"{weak_id} should pass substance"
        else:
            assert out[weak_id] == "side_story", f"{weak_id} should fail substance"


# --- popularity waiver for the weak-anchor keep decision ---------------
#
# A short-duration anchor (fails the duration floor) is normally dropped
# on a plain unseeded title search. The popularity waiver keeps it as its
# own anime IF it still clears the type + episode gates AND has at least
# SUBSTANCE_POPULAR_WAIVER_SCORED_BY MAL scorers ("Love is Like a
# Cocktail": TV, 13 eps, 3 min/ep, ~112k scorers). The waiver is scoped to
# this keep decision only — it must NOT leak into anchor selection or
# relation-type ranking, which stay on the strict substance gate.


def test_popular_short_kept_as_weak_anchor():
    # Osake wa Fuufu ni Natte kara: TV, 13 eps, 3 min/ep, over the scorer
    # floor. Standalone (no cross-link), unseeded title search.
    nodes = {35484: _tv(episodes=13, duration_s=180,
                        scored_by=SUBSTANCE_POPULAR_WAIVER_SCORED_BY)}
    assert not passes_substance(nodes[35484])  # strict gate still fails
    assert passes_popularity_waiver(nodes[35484])
    assert not would_be_dropped_as_weak_anchor(
        nodes, 35484, seed_mal_id=None, cross_link_mal_ids=set(),
    )


def test_obscure_short_still_dropped():
    # Same shape, just under the scorer floor → no waiver → dropped.
    nodes = {999: _tv(episodes=13, duration_s=180,
                     scored_by=SUBSTANCE_POPULAR_WAIVER_SCORED_BY - 1)}
    assert not passes_popularity_waiver(nodes[999])
    assert would_be_dropped_as_weak_anchor(
        nodes, 999, seed_mal_id=None, cross_link_mal_ids=set(),
    )


def test_popularity_waiver_requires_episode_floor():
    # A wildly popular short that fails the EPISODE floor (a 2-ep promo
    # short) is NOT waived — the waiver only relaxes the duration floor.
    nodes = {888: _tv(episodes=SUBSTANCE_MIN_EPISODES - 1, duration_s=180,
                     scored_by=500_000)}
    assert not passes_popularity_waiver(nodes[888])
    assert would_be_dropped_as_weak_anchor(
        nodes, 888, seed_mal_id=None, cross_link_mal_ids=set(),
    )


def test_popularity_waiver_does_not_affect_relation_ranking():
    # The waiver must NOT leak into classify_anime_relations: a popular
    # short sequel to a real TV main is still demoted to side_story by the
    # strict substance gate, and the long TV keeps the anchor.
    nodes = {
        1: _tv(episodes=26, duration_s=1440, aired="2000-01-01", scored_by=50_000),
        2: _tv(episodes=13, duration_s=180, aired="2005-01-01", scored_by=500_000),
    }
    edges = [(1, 2, "sequel")]
    out, anchor = classify_anime_relations(nodes, edges)
    assert anchor == 1
    assert out[1] == "main"
    assert out[2] == "side_story"


# --- feature-length-ONA waiver for the weak-anchor keep decision -------
#
# MAL labels some theatrical / Netflix-original films as ONA, not Movie.
# As an ONA a 1-episode film fails the TV-like episode floor and is
# normally dropped on a plain unseeded title search. The waiver keeps a
# 1-episode ONA whose runtime clears FEATURE_LENGTH_ONA_MIN_DURATION_S as
# its own anime ("Bubble": ONA, 1 ep, 99 min, mal_id 50549). Scoped to the
# keep decision only — like the popularity waiver, it must not touch anchor
# selection or relation-type ranking.


def test_feature_length_ona_kept_as_weak_anchor():
    # Bubble: ONA, 1 ep, 99 min. Standalone, unseeded title search.
    nodes = {50549: _ona(episodes=1, duration_s=5940)}
    assert not passes_substance(nodes[50549])  # strict gate fails (1 ep)
    assert passes_feature_length_ona_waiver(nodes[50549])
    assert not would_be_dropped_as_weak_anchor(
        nodes, 50549, seed_mal_id=None, cross_link_mal_ids=set(),
    )


def test_short_one_episode_ona_still_dropped():
    # "Bubble Beam Berry Blast" (mal_id 59013): ONA, 1 ep, 1 min — a
    # one-shot, not a film. Under the runtime floor → no waiver → dropped.
    nodes = {59013: _ona(episodes=1, duration_s=60)}
    assert not passes_feature_length_ona_waiver(nodes[59013])
    assert would_be_dropped_as_weak_anchor(
        nodes, 59013, seed_mal_id=None, cross_link_mal_ids=set(),
    )


def test_feature_length_ona_waiver_requires_single_episode():
    # A multi-episode ONA that's over the runtime floor per-episode but
    # under the episode floor is NOT a film — the waiver requires exactly
    # 1 episode, so it stays dropped.
    nodes = {777: _ona(episodes=2, duration_s=FEATURE_LENGTH_ONA_MIN_DURATION_S)}
    assert not passes_feature_length_ona_waiver(nodes[777])
    assert would_be_dropped_as_weak_anchor(
        nodes, 777, seed_mal_id=None, cross_link_mal_ids=set(),
    )


def test_feature_length_movie_label_not_treated_as_ona():
    # A genuine Movie (correct MAL label) is handled by the movie duration
    # gate, not this waiver — the waiver is ONA-only.
    nodes = {666: _movie(duration_s=5940)}
    assert not passes_feature_length_ona_waiver(nodes[666])


def test_feature_length_ona_waiver_does_not_affect_relation_ranking():
    # The waiver must NOT leak into classify_anime_relations: a 99-min ONA
    # film that is a side story of a TV main stays side_story; the TV keeps
    # the anchor.
    nodes = {
        1: _tv(episodes=26, duration_s=1440, aired="2000-01-01"),
        2: _ona(episodes=1, duration_s=5940, aired="2005-01-01"),
    }
    edges = [(1, 2, "side_story")]
    out, anchor = classify_anime_relations(nodes, edges)
    assert anchor == 1
    assert out[1] == "main"
    assert out[2] == "side_story"


# --- find_disjoint_franchises: cross-franchise split detection ---------
#
# Pins every contamination shape we identified in the Phase A audit + the
# Phase B Toaru/BNHA scrapes so a future refactor (substance-gate tweak,
# new edge type, anchor-tier change) can't silently re-introduce what we
# just fixed. Two buckets: must-flag (the function returns a non-empty
# list of clusters) and must-NOT-flag (returns []).


def _bnha_like_nodes_and_edges():
    """BNHA + Vigilante shape. Anchor=BNHA S1. Cluster={Vigilante S1, S2}
    via spin-off bridge. The single-cluster reference fixture."""
    nodes = {
        # BNHA chain
        31964: _tv(episodes=13, duration_s=1440, aired="2016-04-03"),
        33486: _tv(episodes=25, duration_s=1440, aired="2017-04-01"),
        36456: _tv(episodes=25, duration_s=1440, aired="2018-04-07"),
        # Vigilante cluster (orphan sub-franchise)
        60593: _tv(episodes=13, duration_s=1440, aired="2025-04-01"),
        61942: _tv(episodes=13, duration_s=1440, aired="2026-01-01"),
    }
    edges = [
        # BNHA main chain
        (31964, 33486, "sequel"),
        (33486, 36456, "sequel"),
        # The contamination bridge (MAL labels Vigilante as a spin-off
        # of BNHA, so v0.14.2 BFS absorbs it as a TERMINAL)
        (31964, 60593, "spin-off"),
        (60593, 31964, "parent_story"),
        # Vigilante's own sequel chain — captured at scrape time thanks
        # to TERMINAL-fetches-relations (Step 1)
        (60593, 61942, "sequel"),
    ]
    return nodes, edges


# --- Must-flag cases ---------------------------------------------------


def test_bnha_vigilante_is_disjoint_franchise():
    nodes, edges = _bnha_like_nodes_and_edges()
    _, anchor = classify_anime_relations(nodes, edges)
    franchises = find_disjoint_franchises(nodes, edges, anchor)

    assert len(franchises) == 1
    cluster = franchises[0]
    assert cluster["member_mal_ids"] == [60593, 61942]
    assert cluster["substance_member_mal_ids"] == [60593, 61942]
    # Vigilante S1 is the oldest TV in the cluster → suggested anchor.
    assert cluster["suggested_anchor_mal_id"] == 60593
    # Bridge edge captures the MAL relation that absorbed the cluster.
    bridge_rels = {rel for _, _, rel in cluster["bridge_edges"]}
    assert "spin-off" in bridge_rels


def test_toaru_index_railgun_is_disjoint_franchise():
    """Toaru Index S1 is the anchor. Railgun S1/S/T form a TV sequel chain
    bridged via `side_story` (MAL's labeling). The classifier doesn't
    pull them into Index's main_chain (they're labeled side_story, not
    sequel/prequel/alt-version), but the BFS now captures Railgun S1's
    sequel chain via TERMINAL-fetches-relations so the splitter has the
    data."""
    nodes = {
        # Index trilogy
        4654: _tv(episodes=24, duration_s=1440, aired="2008-10-04"),
        8937: _tv(episodes=24, duration_s=1440, aired="2010-10-08"),
        36432: _tv(episodes=26, duration_s=1440, aired="2018-10-05"),
        # Railgun cluster
        6213: _tv(episodes=24, duration_s=1440, aired="2009-10-03"),
        16049: _tv(episodes=24, duration_s=1440, aired="2013-04-12"),
        38481: _tv(episodes=25, duration_s=1440, aired="2020-01-10"),
    }
    edges = [
        # Index main chain
        (4654, 8937, "sequel"),
        (8937, 36432, "sequel"),
        # MAL's promiscuous side_story labels: Index S1 lists every
        # Railgun season as a side_story.
        (4654, 6213, "side_story"),
        (4654, 16049, "side_story"),
        (4654, 38481, "side_story"),
        # Railgun's own sequel chain
        (6213, 16049, "sequel"),
        (16049, 38481, "sequel"),
    ]
    _, anchor = classify_anime_relations(nodes, edges)
    assert anchor == 4654

    franchises = find_disjoint_franchises(nodes, edges, anchor)
    assert len(franchises) == 1
    cluster = franchises[0]
    assert set(cluster["member_mal_ids"]) == {6213, 16049, 38481}
    assert cluster["suggested_anchor_mal_id"] == 6213
    bridge_rels = {rel for _, _, rel in cluster["bridge_edges"]}
    assert "side_story" in bridge_rels


def test_pretty_rhythm_multi_franchise_contamination():
    """Worst-case shape from the Phase A audit: Pretty Rhythm anchor +
    three disjoint sub-franchises (PriPara, King of Prism, Pri☆chan)
    each with their own sequel chain. Asserts 3 clusters flagged.
    """
    nodes = {
        # Pretty Rhythm trilogy (anchor chain)
        10257: _tv(episodes=51, duration_s=1440, aired="2011-04-09"),
        12863: _tv(episodes=51, duration_s=1440, aired="2012-04-07"),
        17249: _tv(episodes=51, duration_s=1440, aired="2013-04-06"),
        # PriPara
        23135: _tv(episodes=51, duration_s=1440, aired="2014-07-01"),
        34787: _tv(episodes=51, duration_s=1440, aired="2017-04-04"),
        # King of Prism (theatrical chain — only the TV is here so the
        # cluster qualifies as substance-passing TV-tier members)
        39699: _tv(episodes=12, duration_s=1440, aired="2019-04-08"),
        # Make it ≥2 substance TVs by adding the S2
        51371: _tv(episodes=12, duration_s=1440, aired="2022-01-10"),
        # Kiratto Pri☆chan
        37178: _tv(episodes=51, duration_s=1440, aired="2018-04-08"),
        38804: _tv(episodes=51, duration_s=1440, aired="2019-04-07"),
    }
    edges = [
        # Pretty Rhythm chain
        (10257, 12863, "sequel"),
        (12863, 17249, "sequel"),
        # PriPara cluster — bridged via alternative_setting (MAL's label
        # here, which is dropped at BFS so wouldn't actually appear; the
        # remaining bridge is the spin-off-style `other` edge MAL
        # sometimes emits)
        (10257, 23135, "other"),
        (23135, 34787, "sequel"),
        # King of Prism cluster — bridged via spin-off
        (17249, 39699, "spin-off"),
        (39699, 51371, "sequel"),
        # Pri☆chan cluster — bridged via `other`
        (23135, 37178, "other"),
        (37178, 38804, "sequel"),
    ]
    _, anchor = classify_anime_relations(nodes, edges)
    franchises = find_disjoint_franchises(nodes, edges, anchor)
    assert len(franchises) == 3, (
        f"Expected 3 disjoint sub-franchises, got {len(franchises)}: "
        f"{[f['member_mal_ids'] for f in franchises]}"
    )


def test_qin_shi_mingyue_tunshi_xingkong_orphan_no_bridge_edges():
    """Real Phase A finding: 4-ONA Tunshi Xingkong cluster sits under
    Qin Shi Mingyue with NO direct bridge edges (entered via dropped
    edges to a third party). The cluster still flags because its
    members form a connected substance-passing chain.
    """
    nodes = {
        # QSM chain (3 TVs)
        9806: _tv(episodes=32, duration_s=1440, aired="2007-10-01"),
        11835: _tv(episodes=32, duration_s=1440, aired="2008-10-01"),
        11841: _tv(episodes=32, duration_s=1440, aired="2010-10-01"),
        # Tunshi Xingkong cluster (4 ONAs)
        44218: _ona(episodes=26, duration_s=1440, aired="2020-07-01"),
        49571: _ona(episodes=26, duration_s=1440, aired="2021-07-01"),
        56523: _ona(episodes=26, duration_s=1440, aired="2023-07-01"),
        56524: _ona(episodes=26, duration_s=1440, aired="2024-07-01"),
    }
    edges = [
        # QSM main chain
        (9806, 11835, "sequel"),
        (11835, 11841, "sequel"),
        # Tunshi Xingkong's own chain (no direct edge to QSM — got
        # absorbed via some intermediate node that's not in this graph)
        (44218, 49571, "sequel"),
        (49571, 56523, "sequel"),
        (56523, 56524, "sequel"),
    ]
    _, anchor = classify_anime_relations(nodes, edges)
    franchises = find_disjoint_franchises(nodes, edges, anchor)
    assert len(franchises) == 1
    cluster = franchises[0]
    assert set(cluster["member_mal_ids"]) == {44218, 49571, 56523, 56524}
    assert cluster["bridge_edges"] == [], (
        "Tunshi Xingkong arrived as a structurally-disconnected cluster — "
        "the no-bridge-edges signal is its own diagnostic"
    )


def test_mononoke_2024_movie_trilogy_flagged_after_alternative_setting_drop():
    """The 2024 Mononoke movie trilogy (3 Movies sequel-chained) attaches
    to the original Mononoke TV via `alternative_setting`. That label is
    dropped at BFS, so by the time find_disjoint_franchises runs the
    trilogy has no bridge to the anchored set. The Conan exception
    requires a `parent_story` or `summary` bridge — none exists here, so
    the trilogy flags. Locks in the plan-time decision.
    """
    nodes = {
        # Ayakashi + Mononoke 2007 main chain
        586: _tv(episodes=11, duration_s=1440, aired="2006-01-12"),
        2246: _tv(episodes=12, duration_s=1440, aired="2007-07-13"),
        # 2024 Mononoke movie trilogy — substance via duration
        52107: _movie(duration_s=5400, aired="2024-07-26"),
        59408: _movie(duration_s=5400, aired="2025-01-01"),
        61202: _movie(duration_s=5400, aired="2025-09-01"),
    }
    edges = [
        # Anchor chain
        (586, 2246, "sequel"),
        # Movie trilogy's own sequel chain — no bridge to anchor (alt_setting dropped)
        (52107, 59408, "sequel"),
        (59408, 61202, "sequel"),
    ]
    _, anchor = classify_anime_relations(nodes, edges)
    franchises = find_disjoint_franchises(nodes, edges, anchor)
    assert len(franchises) == 1, (
        "Mononoke 2024 trilogy (no parent_story/summary bridge) MUST flag — "
        "the Conan exception only applies when MAL declares child-of-parent"
    )
    cluster = franchises[0]
    assert set(cluster["member_mal_ids"]) == {52107, 59408, 61202}


# --- Must-NOT-flag cases -----------------------------------------------


def test_fma_brotherhood_2003_alt_version_not_flagged():
    """FMA Brotherhood + 2003 collapsed into one row via alternative_version.
    The 2003 chain lives inside alt_chain (not orphaned), so the splitter
    must not produce a candidate. Pins the v0.14.1 alt-version-as-internal
    decision."""
    nodes = {
        # Brotherhood (anchor) + Conqueror of Shamballa
        5114: _tv(episodes=64, duration_s=1440, aired="2009-04-05"),
        2025: _movie(duration_s=6000, aired="2011-07-02"),
        # 2003 TV + 2005 movie — bridged via alternative_version
        121: _tv(episodes=51, duration_s=1440, aired="2003-10-04"),
        430: _movie(duration_s=6300, aired="2005-07-23"),
    }
    edges = [
        (5114, 2025, "sequel"),
        (5114, 121, "alternative_version"),
        (121, 430, "sequel"),
    ]
    _, anchor = classify_anime_relations(nodes, edges)
    franchises = find_disjoint_franchises(nodes, edges, anchor)
    assert franchises == [], (
        f"Alt-version members must be absorbed into the anchor's alt_chain, "
        f"not flagged as a separate franchise. Got: {franchises}"
    )


def test_higurashi_gou_alt_version_not_flagged():
    """Higurashi 2006 chain + Gou + Sotsu, alt-version bridged. Same shape
    as FMA — alt_chain absorbs Gou/Sotsu, splitter stays quiet."""
    nodes = {
        934: _tv(episodes=26, duration_s=1440, aired="2006-04-04"),   # Higurashi
        1936: _tv(episodes=24, duration_s=1440, aired="2007-07-06"),  # Kai
        41006: _tv(episodes=24, duration_s=1440, aired="2020-10-01"), # Gou
        46100: _tv(episodes=15, duration_s=1440, aired="2021-07-01"), # Sotsu
    }
    edges = [
        (934, 1936, "sequel"),
        (934, 41006, "alternative_version"),
        (41006, 46100, "sequel"),
    ]
    _, anchor = classify_anime_relations(nodes, edges)
    franchises = find_disjoint_franchises(nodes, edges, anchor)
    assert franchises == []


def test_conan_movie_chain_attached_via_parent_story_not_flagged():
    """The Conan false-positive from Phase A: a chain of substance-passing
    Movies attached to the TV main via parent_story/summary edges. They're
    legitimate side-story movies, not a sibling franchise. The Conan
    exception (movies-only + parent_story/summary bridge) keeps the
    splitter quiet."""
    nodes = {
        # Conan TV (main)
        235: _tv(episodes=200, duration_s=1500, aired="1996-01-08"),
        # Two consecutive movies + a summary movie pair
        32005: _movie(duration_s=6300, aired="2016-04-16"),
        35798: _movie(duration_s=6300, aired="2018-04-13"),
        # And a Movie-with-summary pair (Movie 24 + summary)
        39764: _movie(duration_s=6300, aired="2021-04-16"),
        47413: _movie(duration_s=5400, aired="2023-04-14"),
    }
    edges = [
        # Anchor → movies labeled side_story (and back parent_story)
        (235, 32005, "side_story"),
        (32005, 235, "parent_story"),
        (235, 35798, "side_story"),
        (35798, 235, "parent_story"),
        # Movies sequel-chained to each other (the trigger for the
        # disjoint-cluster heuristic before the Conan exception)
        (32005, 35798, "sequel"),
        # The summary movie
        (235, 39764, "side_story"),
        (39764, 235, "parent_story"),
        (235, 47413, "summary"),
        (47413, 235, "full_story"),
        (39764, 47413, "sequel"),
    ]
    _, anchor = classify_anime_relations(nodes, edges)
    franchises = find_disjoint_franchises(nodes, edges, anchor)
    assert franchises == [], (
        f"Conan movie chains attached via parent_story/summary must NOT "
        f"flag — they're legitimate side-stories, not sibling franchises. "
        f"Got: {franchises}"
    )


def test_standalone_substance_side_story_not_flagged():
    """A single substance-passing Movie with no sequel chain of its own
    (Index: Endymion movie shape) does NOT cluster — singletons fall
    below the ≥2 substance-passing-member threshold. Pins that single
    substance-passing orphans don't trigger the splitter."""
    nodes = {
        # Index trilogy + standalone Endymion movie
        4654: _tv(episodes=24, duration_s=1440, aired="2008-10-04"),
        8937: _tv(episodes=24, duration_s=1440, aired="2010-10-08"),
        11743: _movie(duration_s=6000, aired="2013-02-23"),
    }
    edges = [
        (4654, 8937, "sequel"),
        (4654, 11743, "side_story"),
        (11743, 4654, "parent_story"),
    ]
    _, anchor = classify_anime_relations(nodes, edges)
    franchises = find_disjoint_franchises(nodes, edges, anchor)
    assert franchises == []


def test_anime_with_only_main_chain_not_flagged():
    """Trivial happy-path: a clean sequel chain with no other media.
    Pins the no-false-positive-on-the-common-case property."""
    nodes = {
        1: _tv(episodes=12, aired="2015-01-01"),
        2: _tv(episodes=12, aired="2016-01-01"),
        3: _tv(episodes=12, aired="2017-01-01"),
    }
    edges = [(1, 2, "sequel"), (2, 3, "sequel")]
    _, anchor = classify_anime_relations(nodes, edges)
    franchises = find_disjoint_franchises(nodes, edges, anchor)
    assert franchises == []


def test_empty_graph_returns_empty_list():
    """Defensive: empty graph (anchor=None) returns []."""
    assert find_disjoint_franchises({}, [], None) == []


def test_single_substance_orphan_below_threshold_not_flagged():
    """A substance-passing TV reached via side_story but with no sequel
    partner — singleton cluster, falls below the ≥2 threshold. Same as
    the Endymion case but the orphan is TV-tier."""
    nodes = {
        1: _tv(episodes=12, aired="2015-01-01"),
        2: _tv(episodes=12, aired="2016-01-01"),  # main sequel
        3: _tv(episodes=12, aired="2017-01-01"),  # orphan TV, no chain
    }
    edges = [
        (1, 2, "sequel"),
        (1, 3, "side_story"),
    ]
    _, anchor = classify_anime_relations(nodes, edges)
    franchises = find_disjoint_franchises(nodes, edges, anchor)
    assert franchises == [], (
        "A lone substance-passing TV orphan (no sequel partner) is below "
        "the ≥2 threshold — must not flag"
    )
