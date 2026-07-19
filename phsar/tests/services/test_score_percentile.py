"""Confidence-weighted MAL-score percentile (the anime/media "Top N%" chip).

The test DB is shared across rows from other tests, so absolute percentile
values aren't deterministic — but relative ranking is: a higher weighted score
(`score * log10(scored_by + 1)`) can only ever rank better-or-equal, whatever
else is in the catalog. These tests assert that invariant plus the None path.

The anime-level metric is the relation-weighted mean over Main + AlternativeVersion
media only (`RELATION_SCORE_WEIGHTS`); side stories and recaps are excluded. The
anime tests below pin that scoping.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.daos.anime_dao import AnimeDAO
from app.daos.media_dao import MediaDAO
from app.daos.search_filters import (
    weighted_mean_score_expr,
    weighted_mean_votes_expr,
    weighted_score_expr,
)
from app.models.anime import Anime
from app.models.media import Media, RelationType
from app.services.anime_search_service import _compute_anime_aggregates
from app.services.scrape_dispatcher import _weighted_score
from tests._helpers import media_kwargs

anime_dao = AnimeDAO()
media_dao = MediaDAO()


async def test_weighted_score_matches_python_twin(db_session):
    """The SQL `weighted_score_expr` (Postgres `log(10, x)`) and the Python
    `_weighted_score` (`math.log10`) are the two copies of one formula and feed
    the same percentile ranking — they must stay numerically identical. Guards
    against a dialect/refactor that silently desyncs the chip from drift detection.
    """
    anime = Anime(mal_id=95301, title="WeightedTwinAnime")
    db_session.add(anime)
    await db_session.flush()
    media = Media(**media_kwargs(anime.id, 95311, score=7.3, scored_by=4242))
    db_session.add(media)
    await db_session.flush()

    sql_value = (
        await db_session.execute(
            select(weighted_score_expr(Media.score, Media.scored_by)).where(Media.id == media.id)
        )
    ).scalar_one()
    assert sql_value == pytest.approx(_weighted_score(7.3, 4242))


async def test_weighted_mean_matches_python_twin(db_session):
    """The SQL weighted mean (`weighted_mean_score_expr`/`_votes_expr`) and the
    Python twin (`_compute_anime_aggregates`) are two copies of `Σ(w·x)/Σ(w)` over
    `RELATION_SCORE_WEIGHTS` — they must agree numerically (modulo the Python
    display rounding), or the "Top N%" pill would drift from the shown avg. Mirrors
    `test_weighted_score_matches_python_twin` for the scalar formula; guards the
    drift the two structurally-different implementations invite when a weight is
    tuned."""
    anime = Anime(mal_id=95601, title="MeanTwinAnime")
    db_session.add(anime)
    await db_session.flush()
    db_session.add_all([
        Media(**media_kwargs(anime.id, 95611, score=8.0, scored_by=100000)),  # Main
        Media(**media_kwargs(
            anime.id, 95612, score=7.0, scored_by=50000,
            relation_type=RelationType.AlternativeVersion,
        )),
        Media(**media_kwargs(
            anime.id, 95613, score=9.5, scored_by=500000,
            relation_type=RelationType.SideStory,
        )),
        Media(**media_kwargs(
            anime.id, 95614, score=6.0, scored_by=20000,
            relation_type=RelationType.Summary,
        )),
        Media(**media_kwargs(anime.id, 95615, score=None, scored_by=0)),  # unscored Main
    ])
    await db_session.flush()

    # SQL twin: scalar-select the two weighted means for this anime.
    sql_sw, sql_vw = (
        await db_session.execute(
            select(weighted_mean_score_expr(), weighted_mean_votes_expr())
            .where(Media.anime_id == anime.id)
            .group_by(Media.anime_id)
        )
    ).one()

    # Python twin: same media (genre/studio collections loaded for the aggregator).
    media_list = (
        await db_session.execute(
            select(Media)
            .where(Media.anime_id == anime.id)
            .options(selectinload(Media.media_genre), selectinload(Media.media_studio))
        )
    ).scalars().all()
    agg = _compute_anime_aggregates(media_list)

    # Applying the Python display rounding to the SQL result must reproduce it exactly.
    assert agg["avg_score"] == round(float(sql_sw), 2)
    assert agg["avg_scored_by"] == round(float(sql_vw))
    # Only Main (8.0/100k) + Alt (7.0/50k) count → S_w=7.5, V_w=75000.
    assert agg["avg_score"] == pytest.approx(7.5, abs=0.01)
    assert agg["avg_scored_by"] == 75000


async def test_media_score_top_percent_rewards_vote_confidence(db_session):
    anime = Anime(mal_id=95001, title="MediaPercentileAnime")
    db_session.add(anime)
    await db_session.flush()

    # Same raw score, but far more votes → higher weighted metric.
    high = Media(**media_kwargs(anime.id, 95101, score=8.0, scored_by=100000))
    low = Media(**media_kwargs(anime.id, 95102, score=8.0, scored_by=5))
    unscored = Media(**media_kwargs(anime.id, 95103, score=None, scored_by=0))
    db_session.add_all([high, low, unscored])
    await db_session.flush()

    high_pct = await media_dao.score_top_percent(db_session, high.id)
    low_pct = await media_dao.score_top_percent(db_session, low.id)
    unscored_pct = await media_dao.score_top_percent(db_session, unscored.id)

    assert high_pct is not None and 1 <= high_pct <= 100
    assert low_pct is not None
    # More votes at the same score never ranks worse.
    assert high_pct <= low_pct
    # Unscored media has no rank.
    assert unscored_pct is None


async def test_anime_score_top_percent_ranks_and_handles_unscored(db_session):
    strong = Anime(mal_id=95201, title="StrongPercentileAnime")
    weak = Anime(mal_id=95202, title="WeakPercentileAnime")
    unscored = Anime(mal_id=95203, title="UnscoredPercentileAnime")
    db_session.add_all([strong, weak, unscored])
    await db_session.flush()

    db_session.add(Media(**media_kwargs(strong.id, 95211, score=9.0, scored_by=200000)))
    db_session.add(Media(**media_kwargs(weak.id, 95221, score=5.0, scored_by=50)))
    db_session.add(Media(**media_kwargs(unscored.id, 95231, score=None, scored_by=0)))
    await db_session.flush()

    strong_pct = await anime_dao.score_top_percent(db_session, strong.id)
    weak_pct = await anime_dao.score_top_percent(db_session, weak.id)
    unscored_pct = await anime_dao.score_top_percent(db_session, unscored.id)

    assert strong_pct is not None and weak_pct is not None
    assert strong_pct <= weak_pct
    # An anime with no scored media has no rank.
    assert unscored_pct is None


async def test_anime_score_ignores_side_stories(db_session):
    """A scored side story must not change an anime's metric — the score is over
    Main + AlternativeVersion only. Two anime with identical Main media rank
    identically even when one carries a high-vote, high-score side story."""
    base = Anime(mal_id=95401, title="SideBaseAnime")
    plus = Anime(mal_id=95402, title="SidePlusAnime")
    db_session.add_all([base, plus])
    await db_session.flush()

    db_session.add(Media(**media_kwargs(base.id, 95411, score=8.0, scored_by=100000)))
    # Same Main, plus a side story that would dominate if it counted.
    db_session.add(Media(**media_kwargs(plus.id, 95421, score=8.0, scored_by=100000)))
    db_session.add(Media(**media_kwargs(
        plus.id, 95422, score=10.0, scored_by=900000,
        relation_type=RelationType.SideStory,
    )))
    await db_session.flush()

    base_pct = await anime_dao.score_top_percent(db_session, base.id)
    plus_pct = await anime_dao.score_top_percent(db_session, plus.id)
    # Identical Main-only metric → same rank; the side story is invisible to scoring.
    assert base_pct is not None and base_pct == plus_pct


async def test_anime_score_includes_alternative_version(db_session):
    """AlternativeVersion counts as an anchor (like Main). An anime whose only
    scored media is an alt-version still gets a rank; an anime whose only scored
    media is a side story does not."""
    alt_only = Anime(mal_id=95501, title="AltOnlyAnime")
    side_only = Anime(mal_id=95502, title="SideOnlyAnime")
    db_session.add_all([alt_only, side_only])
    await db_session.flush()

    db_session.add(Media(**media_kwargs(
        alt_only.id, 95511, score=8.0, scored_by=100000,
        relation_type=RelationType.AlternativeVersion,
    )))
    db_session.add(Media(**media_kwargs(
        side_only.id, 95521, score=9.0, scored_by=500000,
        relation_type=RelationType.SideStory,
    )))
    await db_session.flush()

    alt_pct = await anime_dao.score_top_percent(db_session, alt_only.id)
    side_pct = await anime_dao.score_top_percent(db_session, side_only.id)
    # Alt-version is an anchor → ranked; side-story-only has no scored anchor → None.
    assert alt_pct is not None and 1 <= alt_pct <= 100
    assert side_pct is None
