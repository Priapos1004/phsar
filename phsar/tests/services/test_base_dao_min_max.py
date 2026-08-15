"""`BaseDAO.get_min_max` — the filter-slider bounds query and its field guard.

The two raises here were inherited from a general field-stats helper that also
computed avg/stddev/median and had no other caller; nothing covered them. They
are the only validation between a field NAME (a string, ultimately from the
filter-options service) and a `func.min`/`func.max` over it, so they're worth
pinning independently of the caller.

Every bounds test SEEDS its own media rather than reading whatever the catalogue
happens to hold. The dev DB is a restored production dump while CI's is empty, so
an assertion about existing rows passes locally and fails in CI — which is exactly
what happened to the first version of this file. Sentinel values sit far outside
any real anime, so `max` is the seeded row in both environments.
"""

import pytest

from app.daos.media_dao import MediaDAO
from app.exceptions import FieldDoesNotExistError, NonNumericFieldError
from app.models.anime import Anime
from app.models.media import Media
from tests._helpers import media_kwargs

media_dao = MediaDAO()

# Deliberately absurd: no real anime has 900k episodes, so `max` is this row
# whether the catalogue is empty or a full production dump. Under PG's int4
# ceiling (2,147,483,647) even multiplied out for `total_watch_time`.
SENTINEL_EPISODES = 900_001
SENTINEL_DURATION = 1_501
SENTINEL_WATCH_TIME = SENTINEL_EPISODES * SENTINEL_DURATION  # 1,351,501,501


@pytest.fixture
async def sentinel_media(db_session):
    """One media whose numeric fields exceed anything in a real catalogue.
    Negative mal_id per the suite-wide convention, so it can't collide with the
    dev DB's real rows on the globally-unique column."""
    anime = Anime(mal_id=-90100, title="A-90100-bounds")
    db_session.add(anime)
    await db_session.flush()
    db_session.add(Media(**media_kwargs(
        anime.id, -9010001,
        episodes=SENTINEL_EPISODES,
        duration_seconds=SENTINEL_DURATION,
    )))
    await db_session.flush()


async def test_get_min_max_returns_bounds_of_a_numeric_column(db_session, sentinel_media):
    low, high = await media_dao.get_min_max(db_session, "episodes")
    assert high == SENTINEL_EPISODES
    assert low is not None and low <= SENTINEL_EPISODES


async def test_get_min_max_accepts_a_hybrid_expression(db_session, sentinel_media):
    """`total_watch_time` is a hybrid with a SQL expression, not a column — it
    reaches the aggregate through the `hasattr` half of the guard rather than
    `mapper.columns`. The media filter-options path depends on this."""
    low, high = await media_dao.get_min_max(db_session, "total_watch_time")
    assert high == SENTINEL_WATCH_TIME
    assert low is not None and low <= SENTINEL_WATCH_TIME


async def test_get_min_max_rejects_an_unknown_field(db_session):
    with pytest.raises(FieldDoesNotExistError):
        await media_dao.get_min_max(db_session, "no_such_column")


async def test_get_min_max_rejects_a_non_numeric_field(db_session):
    """min/max over a text column is valid SQL but meaningless as a slider
    bound, so it's rejected rather than silently returning alphabetical
    extremes."""
    with pytest.raises(NonNumericFieldError):
        await media_dao.get_min_max(db_session, "title")
