"""`BaseDAO.get_min_max` — the filter-slider bounds query and its field guard.

The two raises here were inherited from a general field-stats helper that also
computed avg/stddev/median and had no other caller; nothing covered them. They
are the only validation between a field NAME (a string, ultimately from the
filter-options service) and a `func.min`/`func.max` over it, so they're worth
pinning independently of the caller.
"""

import pytest

from app.daos.media_dao import MediaDAO
from app.exceptions import FieldDoesNotExistError, NonNumericFieldError

media_dao = MediaDAO()


@pytest.mark.asyncio
async def test_get_min_max_returns_bounds_of_a_numeric_column(db_session):
    low, high = await media_dao.get_min_max(db_session, "episodes")
    # The dev DB is a restored prod dump, so bounds exist; assert the shape and
    # ordering rather than specific catalogue values.
    assert low is not None and high is not None
    assert low <= high


@pytest.mark.asyncio
async def test_get_min_max_accepts_a_hybrid_expression(db_session):
    """`total_watch_time` is a hybrid with a SQL expression, not a column — it
    reaches the aggregate through the `hasattr` half of the guard. The media
    filter-options path depends on this."""
    low, high = await media_dao.get_min_max(db_session, "total_watch_time")
    assert low is not None and high is not None
    assert low <= high


@pytest.mark.asyncio
async def test_get_min_max_rejects_an_unknown_field(db_session):
    with pytest.raises(FieldDoesNotExistError):
        await media_dao.get_min_max(db_session, "no_such_column")


@pytest.mark.asyncio
async def test_get_min_max_rejects_a_non_numeric_field(db_session):
    """min/max over a text column is valid SQL but meaningless as a slider
    bound, so it's rejected rather than silently returning alphabetical
    extremes."""
    with pytest.raises(NonNumericFieldError):
        await media_dao.get_min_max(db_session, "title")
