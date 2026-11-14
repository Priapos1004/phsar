"""The `watchlist_events_log` trigger and the migration's seed, against a real database.

A test runs in one transaction, so `now()` is the same for every write in it: an event is
made older by moving its `at`, which is all the merge window reads."""

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text, update

from app.daos.user_dao import UserDAO
from app.models.anime import Anime
from app.models.media import Media
from app.models.ratings import Ratings, WatchStatus
from app.models.tag import Tag
from app.models.watchlist import Watchlist
from app.models.watchlist_event import WatchlistEvent
from tests._helpers import make_user, media_kwargs


@pytest.fixture
async def entry(db_session):
    """A user, a list and one media, nothing listed yet."""
    user = await make_user(db_session, "events-user")
    tag = Tag(user_id=user.id, name="Watchlist", is_default=True)
    other = Tag(user_id=user.id, name="Next")
    anime = Anime(mal_id=-91001, title="A-91001-events")
    db_session.add_all([tag, other, anime])
    await db_session.flush()
    media = Media(**media_kwargs(anime.id, -91001))
    db_session.add(media)
    await db_session.flush()
    return db_session, user, media, tag, other


async def _log(db, user, media):
    rows = (await db.execute(
        select(WatchlistEvent.kind, WatchlistEvent.priority, WatchlistEvent.tag_id)
        .where(WatchlistEvent.user_id == user.id, WatchlistEvent.media_id == media.id)
        .order_by(WatchlistEvent.at, WatchlistEvent.id)
    )).all()
    return [(kind.value, priority, tag) for kind, priority, tag in rows]


async def _list(db, user, media, tag, priority=3):
    db.add(Watchlist(user_id=user.id, media_id=media.id, tag_id=tag.id, priority=priority))
    await db.flush()


async def _set(db, user, media, **values):
    await db.execute(update(Watchlist).where(Watchlist.user_id == user.id, Watchlist.media_id == media.id).values(**values))


async def _unlist(db, user, media):
    await db.execute(delete(Watchlist).where(Watchlist.user_id == user.id, Watchlist.media_id == media.id))


async def _age(db, days):
    """Move every logged event `days` into the past."""
    await db.execute(update(WatchlistEvent).values(at=WatchlistEvent.at - timedelta(days=days)))


async def test_each_write_logs_its_event(entry):
    db, user, media, tag, other = entry
    await _list(db, user, media, tag, priority=3)
    assert await _log(db, user, media) == [("added", 3, tag.id)]
    await _age(db, 10)
    await _set(db, user, media, priority=1)
    await _age(db, 10)
    await _set(db, user, media, tag_id=other.id)
    await _age(db, 10)
    await _unlist(db, user, media)
    assert await _log(db, user, media) == [
        ("added", 3, tag.id), ("changed", 1, tag.id), ("changed", 1, other.id), ("removed", 1, other.id),
    ]


async def test_an_edit_that_changes_neither_priority_nor_list_logs_nothing(entry):
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag)
    await _age(db, 10)
    await _set(db, user, media, priority=3, note="a note")
    assert await _log(db, user, media) == [("added", 3, tag.id)]


async def test_a_quick_toggle_leaves_nothing(entry):
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag)
    await _unlist(db, user, media)
    assert await _log(db, user, media) == []


async def test_removing_and_relisting_as_it_was_leaves_the_listing_untouched(entry):
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag, priority=2)
    await _age(db, 30)
    await _unlist(db, user, media)
    await _list(db, user, media, tag, priority=2)
    assert await _log(db, user, media) == [("added", 2, tag.id)]


async def test_relisting_at_another_priority_becomes_one_change_dated_by_the_relisting(entry):
    """The change is dated when the entry first stood at its new priority."""
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag, priority=2)
    await _age(db, 30)
    await _unlist(db, user, media)
    await _age(db, 2)
    await _list(db, user, media, tag, priority=1)
    assert await _log(db, user, media) == [("added", 2, tag.id), ("changed", 1, tag.id)]
    latest = await db.scalar(select(func.max(WatchlistEvent.at)).where(WatchlistEvent.media_id == media.id))
    assert latest == await db.scalar(select(func.now()))


async def test_priority_churn_collapses_to_at_most_one_change(entry):
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag, priority=1)
    await _age(db, 30)
    for priority in (2, 3):
        await _set(db, user, media, priority=priority)
    assert await _log(db, user, media) == [("added", 1, tag.id), ("changed", 3, tag.id)]
    await _set(db, user, media, priority=1)
    assert await _log(db, user, media) == [("added", 1, tag.id)]


async def test_a_listing_corrected_right_away_stays_one_add(entry):
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag, priority=3)
    await _set(db, user, media, priority=1)
    assert await _log(db, user, media) == [("added", 1, tag.id)]


async def test_a_relisting_after_the_window_is_its_own_event(entry):
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag)
    await _age(db, 30)
    await _unlist(db, user, media)
    await _age(db, 4)
    await _list(db, user, media, tag)
    assert await _log(db, user, media) == [("added", 3, tag.id), ("removed", 3, tag.id), ("added", 3, tag.id)]


async def test_a_rating_in_between_keeps_both_events(entry):
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag)
    await _age(db, 30)
    await _unlist(db, user, media)
    db.add(Ratings(user_id=user.id, media_id=media.id, rating=8.0, watch_status=WatchStatus.completed))
    await db.flush()
    await _list(db, user, media, tag)
    assert await _log(db, user, media) == [("added", 3, tag.id), ("removed", 3, tag.id), ("added", 3, tag.id)]


async def _rated(db, user, media, hours_ago):
    db.add(Ratings(user_id=user.id, media_id=media.id, rating=8.0, watch_status=WatchStatus.completed))
    await db.flush()
    await db.execute(
        update(Ratings).where(Ratings.media_id == media.id)
        .values(modified_at=func.now() - timedelta(hours=hours_ago))
    )


async def test_a_watch_and_the_removal_it_caused_stay_apart_from_a_relisting(entry):
    """Rated, then removed on the rating card, then listed again for a rewatch: three
    events, though the relisting comes within the window of the removal."""
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag)
    await _age(db, 30)
    await _rated(db, user, media, hours_ago=1)
    await _unlist(db, user, media)
    await _list(db, user, media, tag)
    assert await _log(db, user, media) == [("added", 3, tag.id), ("removed", 3, tag.id), ("added", 3, tag.id)]


async def test_a_rating_just_before_the_span_still_keeps_its_events(entry):
    """A rating two hours before a priority change that a removal and a relisting then
    follow: close enough to belong with them, so nothing merges."""
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag)
    await _age(db, 30)
    await _set(db, user, media, priority=1)
    await _age(db, 1 / 24)
    await _rated(db, user, media, hours_ago=2)
    await _unlist(db, user, media)
    await _list(db, user, media, tag, priority=1)
    assert [kind for kind, *_ in await _log(db, user, media)] == ["added", "changed", "removed", "added"]


async def test_deleting_the_user_or_the_media_leaves_no_events_and_no_error(entry):
    db, user, media, tag, _ = entry
    await _list(db, user, media, tag)
    await db.execute(delete(Media).where(Media.id == media.id))
    assert await db.scalar(select(func.count()).select_from(WatchlistEvent).where(WatchlistEvent.user_id == user.id)) == 0

    anime = Anime(mal_id=-91002, title="A-91002-events")
    db.add(anime)
    await db.flush()
    second = Media(**media_kwargs(anime.id, -91002))
    db.add(second)
    await db.flush()
    await _list(db, user, second, tag)
    await UserDAO().delete(db, user)
    assert await db.scalar(select(func.count()).select_from(WatchlistEvent).where(WatchlistEvent.media_id == second.id)) == 0


async def test_the_migration_seeds_every_entry_as_found(entry):
    """An entry edited after it was listed seeds an add at its listing and a change at its
    edit; one never edited, the add alone."""
    db, user, media, tag, other = entry
    await _list(db, user, media, tag, priority=2)
    await db.execute(text("ALTER TABLE watchlist DISABLE TRIGGER watchlist_events_log"))
    await db.execute(delete(WatchlistEvent))
    created = await db.scalar(select(Watchlist.created_at).where(Watchlist.media_id == media.id))
    await _set(db, user, media, tag_id=other.id, modified_at=created + timedelta(days=5))
    path = next((Path(__file__).parents[2] / "alembic" / "versions").glob("4b7e1c9d2a60_*.py"))
    spec = importlib.util.spec_from_file_location("seed_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    await db.execute(text(migration.SEED))
    await db.execute(text("ALTER TABLE watchlist ENABLE TRIGGER watchlist_events_log"))
    rows = (await db.execute(
        select(WatchlistEvent.kind, WatchlistEvent.tag_id, WatchlistEvent.at)
        .where(WatchlistEvent.user_id == user.id).order_by(WatchlistEvent.at)
    )).all()
    assert [(k.value, t, at - created) for k, t, at in rows] == [
        ("added", other.id, timedelta(0)), ("changed", other.id, timedelta(days=5)),
    ]
