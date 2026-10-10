"""seed_browse — the core carousels synced from the repo lists on every boot.

Runs against whatever the database already holds (a booted dev DB has the rows,
CI's is empty), so each test seeds once to reach a known state before it acts.
"""

from sqlalchemy import event, select
from sqlalchemy.orm import selectinload

from app.models.browse import BrowseCarousel, BrowseFilterSet, CarouselFilterSet
from app.seeders import browse_seeder
from app.seeders.browse_seeder import CAROUSELS, FILTER_SETS, seed_browse


async def _state(db_session) -> dict[str, tuple]:
    """Each carousel's (id, title, [(set key, link id, default_on, position)])."""
    stmt = select(BrowseCarousel).options(
        selectinload(BrowseCarousel.filter_sets).selectinload(CarouselFilterSet.filter_set),
    ).execution_options(populate_existing=True)
    return {
        c.key: (c.id, c.title, [(lk.filter_set.key, lk.id, lk.default_on, lk.position) for lk in c.filter_sets])
        for c in (await db_session.execute(stmt)).scalars().all()
    }


async def test_a_second_seed_writes_nothing(db_session, db_engine):
    """Every boot re-runs the seed, so an unchanged list must cost no write — and leave
    `modified_at` meaning when a definition last changed."""
    await seed_browse(db_session)
    before = await _state(db_session)
    writes: list[str] = []

    def record(conn, cursor, statement, *args):
        if statement.lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", record)
    try:
        await seed_browse(db_session)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", record)
    assert writes == []
    assert await _state(db_session) == before
    assert set(before) == {c.key for c in CAROUSELS}


async def test_a_changed_definition_updates_in_place(db_session, monkeypatch):
    """Same rows, new values: a link that stays keeps its id, so anything referencing it survives."""
    await seed_browse(db_session)
    before = await _state(db_session)
    first, *rest = CAROUSELS
    flipped = [(key, not on) for key, on in reversed(first.filter_sets)]
    monkeypatch.setattr(browse_seeder, "CAROUSELS", [first._replace(title="Renamed", filter_sets=flipped), *rest])
    await seed_browse(db_session)

    after = await _state(db_session)
    carousel_id, title, links = after[first.key]
    assert (carousel_id, title) == (before[first.key][0], "Renamed")
    link_ids = {key: link_id for key, link_id, _, _ in before[first.key][2]}
    assert links == [(key, link_ids[key], on, position) for position, (key, on) in enumerate(flipped)]


async def test_what_the_lists_drop_is_deleted(db_session, monkeypatch):
    """A dropped carousel goes, and so does a dropped set with every link to it."""
    await seed_browse(db_session)
    dropped_set = FILTER_SETS[-1].key
    kept = [c._replace(filter_sets=[s for s in c.filter_sets if s[0] != dropped_set]) for c in CAROUSELS[1:]]
    monkeypatch.setattr(browse_seeder, "CAROUSELS", kept)
    monkeypatch.setattr(browse_seeder, "FILTER_SETS", FILTER_SETS[:-1])
    await seed_browse(db_session)

    after = await _state(db_session)
    assert set(after) == {c.key for c in kept}
    assert all(key != dropped_set for _, _, links in after.values() for key, *_ in links)
    sets = (await db_session.execute(select(BrowseFilterSet.key))).scalars().all()
    assert dropped_set not in sets
