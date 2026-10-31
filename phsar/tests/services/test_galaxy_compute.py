"""`galaxy_compute` on a synthetic catalogue: clusters of anime, each with its own synopsis
direction, tags and studio, and some still airing so the fit has anime to place. Several
small clusters rather than a few big ones, because the fit caps a sector's size
(`MAX_SECTOR_FRACTION`).
The real catalogue's shape is a study, not a test — these pin the structure: every star
gets a sector and a region inside it, placement answers in the fit's labels, a refit
starts from the old layout, and hand names follow their members."""

import numpy as np
import pytest

from app.services.galaxy_compute import AnimeRow, MediaRow, carry_names, fit, place

_CLUSTERS = [
    (genre, demo, f"Studio {i}", source)
    for i, (genre, demo, source) in enumerate([
        ("Action", "Shounen", "Manga"), ("Romance", "Shoujo", "Light novel"),
        ("Mecha", "Seinen", "Original"), ("Comedy", "Kids", "Manga"),
        ("Horror", "Seinen", "Web novel"), ("Sports", "Shounen", "Manga"),
        ("Music", "Shoujo", "Original"), ("Fantasy", "Josei", "Light novel"),
    ])
]


def _catalogue() -> tuple[list[AnimeRow], list[MediaRow]]:
    per_cluster = 35
    rng = np.random.default_rng(0)
    centres = rng.normal(size=(len(_CLUSTERS), 384))
    anime, media = [], []
    for c, (genre, demo, studio, source) in enumerate(_CLUSTERS):
        for k in range(per_cluster):
            anime_id = 1 + c * per_cluster + k
            finished = k % 9 != 0
            score = float(rng.uniform(6, 9)) if finished else None
            anime.append(AnimeRow(
                anime_id, (centres[c] + rng.normal(scale=0.6, size=384)).tolist(),
                score, float(rng.integers(1000, 100000)) if finished else None,
            ))
            media.append(MediaRow(
                anime_id=anime_id, main=True, settled=finished, media_type="TV",
                age=13, source=source, watch_seconds=12 * 1440, season_year=int(rng.integers(1995, 2026)),
                tags=((genre, "genres"), (demo, "demographics")), studios=(studio,),
            ))
    return anime, media


@pytest.fixture(scope="module")
def fitted():
    anime, media = _catalogue()
    return anime, media, fit(anime, media, {})


def test_every_star_sits_in_a_region_of_its_sector(fitted):
    anime, _, result = fitted
    sectors = {g["number"] for g in result["groups"] if g["level"] == "sector"}
    parent = {g["number"]: g["parent"] for g in result["groups"] if g["level"] == "region"}
    assert len(result["stars"]) == len(anime)
    assert {s["sector"] for s in result["stars"]} <= sectors
    assert all(parent[s["region"]] == s["sector"] for s in result["stars"])
    # Airing anime are placed, not fitted from.
    assert sum(not s["trained"] for s in result["stars"]) == result["summary"]["predicted"] > 0


def test_placement_answers_in_the_fits_labels(fitted):
    anime, media, result = fitted
    stars = place(result["blob"], anime[:30], media)
    fitted_sector = {s["anime_id"]: s["sector"] for s in result["stars"]}
    assert all(not s["trained"] for s in stars)
    # A fitted anime placed again mostly lands where the fit put it.
    assert sum(s["sector"] == fitted_sector[s["anime_id"]] for s in stars) >= 24


def test_a_refit_from_the_live_layout_reports_its_movement(fitted):
    """A refit with newcomers (anime missing from `previous`, who start beside their
    nearest known stars) runs and reports how far the median star moved. It cannot show
    the warm start keeps stars still: with the same seed a cold refit reproduces the
    layout too. That is measured on the real catalogue (the v0.16.5 compound doc)."""
    anime, media, result = fitted
    previous = {s["anime_id"]: ([s["x"], s["y"]], s["z10"]) for s in result["stars"][10:]}
    assert fit(anime, media, previous)["summary"]["median_movement"] is not None


def test_hand_names_follow_their_members_one_to_one():
    previous = [
        ("sector", frozenset({1, 2, 3, 4}), "Isekai"),
        ("sector", frozenset({1, 2, 3}), "Close second"),
        ("region", frozenset({1, 2}), "Cheat skills"),
        ("sector", frozenset({90, 91}), "Gone"),
    ]
    new = [
        ("sector", frozenset({1, 2, 3, 5})),
        ("region", frozenset({1, 2})),
        ("region", frozenset({90, 91})),
    ]
    # "Isekai" (Jaccard 0.6) and "Close second" (0.75) both want the first sector; the
    # better overlap wins and the other goes unplaced. A region never takes a sector's
    # name, and a group no one overlaps keeps its auto name.
    assert carry_names(previous, new) == {0: "Close second", 1: "Cheat skills"}
