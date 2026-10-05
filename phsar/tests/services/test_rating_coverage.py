"""Rated-coverage tiers — the per-anime "how much of this have I rated" state.

Every case drives `rating_service.get_rating_coverage`, so each one covers the
grouped query in `RatingDAO.get_anime_coverage` and the ladder in
`_coverage_tier` together. That is deliberate: the two halves are only
meaningful as a pair, and a tier is the only thing either half exists to
produce.

Pins: the tier ordering; that `dropped`/`on_hold` hold an anime at `some`; that
a not-yet-aired media leaves both numerator and denominator; the
at-least-one-aired-main guard that stops a side story earning `all`; and that
an untouched anime is absent rather than reported untouched.
"""

import pytest

from app.models.anime import Anime
from app.models.media import Media, RelationType
from app.models.ratings import Ratings, WatchStatus
from app.schemas.rating_schema import CoverageTier
from app.services import rating_service
from tests._helpers import make_user, media_kwargs


async def _anime(db, mal_seed: int, *specs) -> tuple:
    """One anime whose media are described by `(relation_type, airing_status)`."""
    anime = Anime(mal_id=mal_seed, title=f"A{mal_seed}")
    db.add(anime)
    await db.flush()
    media = [
        Media(**media_kwargs(anime.id, mal_seed - i - 1, relation_type=rel, airing_status=status))
        for i, (rel, status) in enumerate(specs)
    ]
    db.add_all(media)
    await db.flush()
    return anime, media


def _rate(db, user, media, status=WatchStatus.completed):
    db.add(Ratings(user_id=user.id, media_id=media.id, rating=8.0, watch_status=status))


async def _tier(db, user, anime_uuid) -> CoverageTier | None:
    rows = await rating_service.get_rating_coverage(db, user.id)
    return next((r.tier for r in rows if r.anime_uuid == anime_uuid), None)


async def test_all_media_completed_reports_all(db_session):
    user = await make_user(db_session, "cov_all")
    anime, media = await _anime(
        db_session, -91000,
        (RelationType.Main, "Finished Airing"), (RelationType.SideStory, "Finished Airing"),
    )
    for m in media:
        _rate(db_session, user, m)
    await db_session.flush()
    assert await _tier(db_session, user, anime.uuid) == CoverageTier.all


async def test_unrated_side_story_holds_the_anime_at_main(db_session):
    user = await make_user(db_session, "cov_main")
    anime, media = await _anime(
        db_session, -91100,
        (RelationType.Main, "Finished Airing"), (RelationType.SideStory, "Finished Airing"),
    )
    _rate(db_session, user, media[0])
    await db_session.flush()
    assert await _tier(db_session, user, anime.uuid) == CoverageTier.main


@pytest.mark.parametrize(
    ("status", "seed"), [(WatchStatus.dropped, -91200), (WatchStatus.on_hold, -91300)],
)
async def test_an_incomplete_main_falls_back_to_some(db_session, status, seed):
    user = await make_user(db_session, f"cov_{status.value}")
    anime, media = await _anime(db_session, seed, (RelationType.Main, "Finished Airing"))
    _rate(db_session, user, media[0], status)
    await db_session.flush()
    assert await _tier(db_session, user, anime.uuid) == CoverageTier.some


async def test_dropped_side_story_still_leaves_main_reachable(db_session):
    """Bailing on a side story is not bailing on the story, so `main` survives —
    but it is still an incomplete media, so `all` does not."""
    user = await make_user(db_session, "cov_dropped_side")
    anime, media = await _anime(
        db_session, -91400,
        (RelationType.Main, "Finished Airing"), (RelationType.SideStory, "Finished Airing"),
    )
    _rate(db_session, user, media[0])
    _rate(db_session, user, media[1], WatchStatus.dropped)
    await db_session.flush()
    assert await _tier(db_session, user, anime.uuid) == CoverageTier.main


async def test_not_yet_aired_media_leaves_the_denominator(db_session):
    """An announced sequel must not hold a finished anime below `all` — nobody can
    rate it, so `all` would be unreachable for every active franchise."""
    user = await make_user(db_session, "cov_unaired")
    anime, media = await _anime(
        db_session, -91500,
        (RelationType.Main, "Finished Airing"), (RelationType.Main, "Not yet aired"),
    )
    _rate(db_session, user, media[0])
    await db_session.flush()
    assert await _tier(db_session, user, anime.uuid) == CoverageTier.all


async def test_currently_airing_media_counts(db_session):
    """Episode 1 is out, so it is rateable and therefore owed."""
    user = await make_user(db_session, "cov_airing")
    anime, media = await _anime(
        db_session, -91600,
        (RelationType.Main, "Finished Airing"), (RelationType.Main, "Currently Airing"),
    )
    _rate(db_session, user, media[0])
    await db_session.flush()
    assert await _tier(db_session, user, anime.uuid) == CoverageTier.some


async def test_completed_side_story_under_an_unaired_main_stays_some(db_session):
    user = await make_user(db_session, "cov_no_main")
    anime, media = await _anime(
        db_session, -91700,
        (RelationType.Main, "Not yet aired"), (RelationType.SideStory, "Finished Airing"),
    )
    _rate(db_session, user, media[1])
    await db_session.flush()
    assert await _tier(db_session, user, anime.uuid) == CoverageTier.some


async def test_alternative_version_counts_as_main_story(db_session):
    """`main` is MAIN_STORY_RELATIONS, not RelationType.Main — a retelling is part
    of the story, and the spoiler frontier and MAL score already read it that way."""
    user = await make_user(db_session, "cov_alt")
    anime, media = await _anime(
        db_session, -91800,
        (RelationType.Main, "Finished Airing"),
        (RelationType.AlternativeVersion, "Finished Airing"),
    )
    _rate(db_session, user, media[0])
    await db_session.flush()
    assert await _tier(db_session, user, anime.uuid) == CoverageTier.some


async def test_untouched_anime_is_absent_from_the_response(db_session):
    user = await make_user(db_session, "cov_absent")
    anime, _ = await _anime(db_session, -91900, (RelationType.Main, "Finished Airing"))
    assert await _tier(db_session, user, anime.uuid) is None


async def test_coverage_is_scoped_to_the_caller(db_session):
    user = await make_user(db_session, "cov_owner")
    other = await make_user(db_session, "cov_other")
    anime, media = await _anime(db_session, -92000, (RelationType.Main, "Finished Airing"))
    _rate(db_session, user, media[0])
    await db_session.flush()
    assert await _tier(db_session, user, anime.uuid) == CoverageTier.all
    assert await _tier(db_session, other, anime.uuid) is None
