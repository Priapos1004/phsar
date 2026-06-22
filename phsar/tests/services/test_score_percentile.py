"""Confidence-weighted MAL-score percentile (the anime/media "Top N%" chip).

The test DB is shared across rows from other tests, so absolute percentile
values aren't deterministic — but relative ranking is: a higher weighted score
(`score * log10(scored_by + 1)`) can only ever rank better-or-equal, whatever
else is in the catalog. These tests assert that invariant plus the None path.
"""

from app.daos.anime_dao import AnimeDAO
from app.daos.media_dao import MediaDAO
from app.models.anime import Anime
from app.models.media import Media
from tests._helpers import media_kwargs

anime_dao = AnimeDAO()
media_dao = MediaDAO()


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
