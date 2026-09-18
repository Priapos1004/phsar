"""Tests for delete_candidate_service: the dismiss / remove / blacklist lifecycle.

The thing worth pinning here is that removal is media-grained. Deleting one dead
entry out of a real franchise must leave the rest alone, and deleting the last
one must take the (now empty) anime with it — those are opposite outcomes from
the same code path, so both are asserted.

Blacklisting is the other load-bearing bit: `media_unwanted` has no FK to media,
which is the only reason the blacklist row survives the delete cascade. A test
that wrote the row and never looked again would pass even if that broke.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.daos.delete_candidate_dao import DeleteCandidateDAO
from app.exceptions import (
    CurationConfirmationMismatchError,
    DeleteCandidateAlreadyResolvedError,
    DeleteCandidateNotFoundError,
)
from app.models.anime import Anime
from app.models.delete_candidate import DeleteCandidate, DeleteCandidateStatus
from app.models.media import Media, RelationType
from app.models.media_unwanted import MediaUnwanted
from app.services.delete_candidate_service import (
    BLACKLIST_REASON,
    DETECTED_BY_LOW_SIGNAL,
    DETECTED_BY_SWEEP_404,
    delete_decision,
    detect_low_signal_candidates,
    dismiss,
    list_dismissed,
    list_pending,
    remove,
)
from tests._helpers import media_kwargs

ADMIN = "admin-user"


async def _make_anime_with_media(db_session, *, mal_base: int, count: int) -> Anime:
    anime = Anime(mal_id=mal_base, title=f"A{mal_base}")
    db_session.add(anime)
    await db_session.flush()
    for i in range(count):
        db_session.add(
            Media(**media_kwargs(
                anime.id, mal_base + i, title=f"M{mal_base + i}",
                relation_type=RelationType.Main if i == 0 else RelationType.SideStory,
            ))
        )
    await db_session.flush()
    return anime


async def _candidate_for(db_session, media: Media, detected_by=DETECTED_BY_SWEEP_404):
    candidate = DeleteCandidate(
        media_id=media.id,
        mal_id=media.mal_id,
        title=media.title,
        name_eng=media.name_eng,
        name_jap=media.name_jap,
        detected_by=detected_by,
        status=DeleteCandidateStatus.pending,
    )
    db_session.add(candidate)
    await db_session.flush()
    return candidate


async def _media_for(db_session, anime_id: int) -> list[Media]:
    return list(
        (
            await db_session.execute(
                select(Media).where(Media.anime_id == anime_id).order_by(Media.id)
            )
        ).scalars().all()
    )


async def test_dismiss_flips_status_and_keeps_the_media(db_session):
    anime = await _make_anime_with_media(db_session, mal_base=970100, count=1)
    media = (await _media_for(db_session, anime.id))[0]
    candidate = await _candidate_for(db_session, media)

    await dismiss(db_session, candidate.uuid)

    await db_session.refresh(candidate)
    assert candidate.status == DeleteCandidateStatus.dismissed
    # The whole point of dismiss: nothing else moved.
    assert len(await _media_for(db_session, anime.id)) == 1


async def test_remove_deletes_one_media_and_leaves_its_siblings(db_session):
    """The Conan case: MAL deleted one entry out of a large franchise. Removing
    it must leave every sibling alone."""
    anime = await _make_anime_with_media(db_session, mal_base=970200, count=3)
    media = await _media_for(db_session, anime.id)
    victim = media[2]
    candidate = await _candidate_for(db_session, victim)

    await remove(
        db_session, candidate.uuid,
        confirm=ADMIN, username=ADMIN, blacklist=False,
    )

    surviving = await _media_for(db_session, anime.id)
    assert [m.mal_id for m in surviving] == [970200, 970201]
    # The anime itself stays — it still has media.
    assert await db_session.get(Anime, anime.id) is not None
    await db_session.refresh(candidate)
    assert candidate.status == DeleteCandidateStatus.deleted
    assert candidate.blacklisted is False


async def test_remove_last_media_deletes_the_empty_anime(db_session):
    """The Niu Lai case: a standalone entry. Nothing in the catalogue holds an
    anime with zero media, so the umbrella has to go with it."""
    anime = await _make_anime_with_media(db_session, mal_base=970300, count=1)
    media = (await _media_for(db_session, anime.id))[0]
    candidate = await _candidate_for(db_session, media)
    anime_id = anime.id

    await remove(
        db_session, candidate.uuid,
        confirm=ADMIN, username=ADMIN, blacklist=False,
    )

    assert await db_session.get(Anime, anime_id) is None
    assert await _media_for(db_session, anime_id) == []


async def test_blacklist_row_survives_the_delete_cascade(db_session):
    """`media_unwanted` carries no FK to media precisely so the row outlives
    the delete. If someone adds one, this is what catches it."""
    anime = await _make_anime_with_media(db_session, mal_base=970400, count=1)
    media = (await _media_for(db_session, anime.id))[0]
    mal_id = media.mal_id
    candidate = await _candidate_for(db_session, media)

    await remove(
        db_session, candidate.uuid,
        confirm=ADMIN, username=ADMIN, blacklist=True,
    )

    row = (
        await db_session.execute(
            select(MediaUnwanted).where(MediaUnwanted.mal_id == mal_id)
        )
    ).scalars().first()
    assert row is not None, "blacklist row was cascaded away with the media"
    assert row.reason == BLACKLIST_REASON
    # String(20) on the column — a longer reason is a silent migration.
    assert len(BLACKLIST_REASON) <= 20
    await db_session.refresh(candidate)
    assert candidate.blacklisted is True


async def test_candidate_row_outlives_the_media_it_records(db_session):
    """SET NULL, not CASCADE. The audit trail has to survive the deletion it
    describes — CASCADE would erase it exactly when it becomes the only record."""
    anime = await _make_anime_with_media(db_session, mal_base=970500, count=1)
    media = (await _media_for(db_session, anime.id))[0]
    candidate = await _candidate_for(db_session, media)
    candidate_id = candidate.id

    await remove(
        db_session, candidate.uuid,
        confirm=ADMIN, username=ADMIN, blacklist=False,
    )

    row = await db_session.get(DeleteCandidate, candidate_id)
    assert row is not None
    assert row.media_id is None
    # The snapshot is what is left to identify it by.
    assert row.mal_id == 970500
    assert row.title == "M970500"


async def test_remove_rejects_a_confirm_that_is_not_the_username(db_session):
    anime = await _make_anime_with_media(db_session, mal_base=970600, count=1)
    media = (await _media_for(db_session, anime.id))[0]
    candidate = await _candidate_for(db_session, media)

    with pytest.raises(CurationConfirmationMismatchError):
        await remove(
            db_session, candidate.uuid,
            confirm="not-the-admin", username=ADMIN, blacklist=False,
        )

    # And nothing happened.
    assert len(await _media_for(db_session, anime.id)) == 1
    await db_session.refresh(candidate)
    assert candidate.status == DeleteCandidateStatus.pending


async def test_resolving_a_resolved_candidate_is_a_conflict(db_session):
    anime = await _make_anime_with_media(db_session, mal_base=970700, count=2)
    media = (await _media_for(db_session, anime.id))[0]
    candidate = await _candidate_for(db_session, media)
    await dismiss(db_session, candidate.uuid)

    with pytest.raises(DeleteCandidateAlreadyResolvedError):
        await dismiss(db_session, candidate.uuid)
    with pytest.raises(DeleteCandidateAlreadyResolvedError):
        await remove(
            db_session, candidate.uuid,
            confirm=ADMIN, username=ADMIN, blacklist=False,
        )


async def test_delete_decision_only_accepts_dismissed_rows(db_session):
    """A deleted row is the audit record of a removal and must not be erasable
    from the UI; a pending row belongs to the live queue."""
    anime = await _make_anime_with_media(db_session, mal_base=970800, count=1)
    media = (await _media_for(db_session, anime.id))[0]
    candidate = await _candidate_for(db_session, media)

    with pytest.raises(DeleteCandidateNotFoundError):
        await delete_decision(db_session, candidate.uuid)

    await dismiss(db_session, candidate.uuid)
    await delete_decision(db_session, candidate.uuid)
    assert await DeleteCandidateDAO().get_by_uuid(db_session, candidate.uuid) is None


async def test_dismissed_mal_id_is_not_re_raised_by_detection(db_session):
    """The suppression that makes a dismissal mean anything: without it the next
    detection re-raises the row the admin just chose to keep, every night."""
    anime = await _make_anime_with_media(db_session, mal_base=970900, count=1)
    media = (await _media_for(db_session, anime.id))[0]
    media.score = None
    media.scored_by = 3
    # Old enough to clear the age floor; this test is about stickiness, not age.
    media.aired_from = date.today() - timedelta(days=800)
    await db_session.flush()

    first = await detect_low_signal_candidates(db_session)
    assert first >= 1
    raised = (
        await db_session.execute(
            select(DeleteCandidate).where(DeleteCandidate.mal_id == 970900)
        )
    ).scalars().one()
    assert raised.detected_by == DETECTED_BY_LOW_SIGNAL

    await dismiss(db_session, raised.uuid)

    # Re-running detection must not resurrect it.
    await detect_low_signal_candidates(db_session)
    rows = (
        await db_session.execute(
            select(DeleteCandidate).where(DeleteCandidate.mal_id == 970900)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == DeleteCandidateStatus.dismissed


async def test_low_signal_skips_an_entry_too_young_to_have_votes(db_session):
    """A current-season entry has barely been seen. Flagging it reads its empty
    vote count as a verdict when it is only earliness — the exact case that put
    the age floor there, since MAL votes accrue for months after a premiere."""
    recent = await _make_anime_with_media(db_session, mal_base=971300, count=1)
    old = await _make_anime_with_media(db_session, mal_base=971400, count=1)
    undated = await _make_anime_with_media(db_session, mal_base=971500, count=1)
    today = date.today()
    for anime, aired in (
        (recent, today - timedelta(days=60)),
        (old, today - timedelta(days=800)),
        (undated, None),
    ):
        for media in await _media_for(db_session, anime.id):
            media.score, media.scored_by, media.aired_from = None, 2, aired
    await db_session.flush()

    await detect_low_signal_candidates(db_session)

    flagged = {
        row.mal_id
        for row in (
            await db_session.execute(
                select(DeleteCandidate).where(
                    DeleteCandidate.mal_id.in_([971300, 971400, 971500])
                )
            )
        ).scalars().all()
    }
    # The old one only. The undated one falls out with the young one: a NULL
    # aired_from cannot be aged, and deletion is the wrong place to guess.
    assert flagged == {971400}


async def test_low_signal_skips_a_no_score_entry_inside_a_real_franchise(db_session):
    """A franchise's unrated OVA is a side-entry of something real. Only an
    anime whose ONLY media never drew votes is seasonal-sweep noise."""
    solo = await _make_anime_with_media(db_session, mal_base=971000, count=1)
    franchise = await _make_anime_with_media(db_session, mal_base=971100, count=3)
    aged = date.today() - timedelta(days=800)
    for media in await _media_for(db_session, solo.id):
        media.score, media.scored_by, media.aired_from = None, 2, aged
    for media in await _media_for(db_session, franchise.id):
        media.score, media.scored_by, media.aired_from = None, 2, aged
    await db_session.flush()

    await detect_low_signal_candidates(db_session)

    flagged = {
        row.mal_id
        for row in (
            await db_session.execute(
                select(DeleteCandidate).where(
                    DeleteCandidate.mal_id.in_([971000, 971100, 971101, 971102])
                )
            )
        ).scalars().all()
    }
    assert flagged == {971000}


async def test_lists_report_user_data_and_franchise_context(db_session):
    anime = await _make_anime_with_media(db_session, mal_base=971200, count=4)
    media = (await _media_for(db_session, anime.id))[1]
    candidate = await _candidate_for(db_session, media)

    pending = await list_pending(db_session)
    item = next(i for i in pending if i.uuid == str(candidate.uuid))
    assert item.anime_media_count == 4
    assert item.anime_title == anime.title
    assert item.rating_count == 0
    assert item.watchlist_count == 0
    # sweep_404 rows deliberately withhold the stale vote count.
    assert item.detected_by == DETECTED_BY_SWEEP_404
    assert item.scored_by is None
    assert item.dismissed_at is None

    await dismiss(db_session, candidate.uuid)
    dismissed = await list_dismissed(db_session)
    assert next(i for i in dismissed if i.uuid == str(candidate.uuid)).dismissed_at is not None

async def test_a_deleted_row_does_not_blind_detection_to_a_re_added_entry(db_session):
    """The off-by-default blacklist checkbox is only safe because a re-added entry
    comes back to this queue. A `deleted` row is an audit record, and nothing in the
    API or the UI can clear it — so if it suppressed detection too, declining to
    blacklist would strand the entry in the catalogue permanently: no queue row, and
    no way to raise one. Blacklisting, not the audit row, is what makes it stay gone.
    """
    anime = await _make_anime_with_media(db_session, mal_base=971300, count=1)
    media = (await _media_for(db_session, anime.id))[0]
    candidate = await _candidate_for(db_session, media)
    await remove(
        db_session, candidate.uuid,
        confirm=ADMIN, username=ADMIN, blacklist=False,
    )
    resolved = await DeleteCandidateDAO().get_by_uuid(db_session, candidate.uuid)
    assert resolved.status == DeleteCandidateStatus.deleted

    # MAL re-lists it and a scrape brings the same mal_id back on a fresh anime.
    readded = Anime(mal_id=971399, title="A971399")
    db_session.add(readded)
    await db_session.flush()
    db_session.add(Media(**media_kwargs(
        readded.id, 971300, title="M971300-readded", relation_type=RelationType.Main,
        score=None, scored_by=2, aired_from=date.today() - timedelta(days=800),
    )))
    await db_session.flush()

    await detect_low_signal_candidates(db_session)
    statuses = {
        row.status
        for row in (
            await db_session.execute(
                select(DeleteCandidate).where(DeleteCandidate.mal_id == 971300)
            )
        ).scalars().all()
    }
    assert DeleteCandidateStatus.pending in statuses, (
        "a deleted audit row must not suppress rediscovery of a re-added entry"
    )


async def test_removing_a_media_recomputes_the_surviving_animes_spoiler_cache(
    db_session, monkeypatch,
):
    """Removal is media-grained, so a surviving anime's frontier moves: the entries
    after the deleted one become reachable. Every other catalogue-mutating path
    recomputes, and a stale cache here is not self-healing — the startup backfill
    only seeds users who have no rows at all.
    """
    from app.services import delete_candidate_service

    recomputed: list[set[int]] = []

    async def _spy(_db, anime_ids):
        recomputed.append(set(anime_ids))

    monkeypatch.setattr(
        delete_candidate_service, "refresh_spoiler_cache_for_anime_ids", _spy
    )

    anime = await _make_anime_with_media(db_session, mal_base=971400, count=3)
    media = (await _media_for(db_session, anime.id))[1]
    candidate = await _candidate_for(db_session, media)
    await remove(
        db_session, candidate.uuid,
        confirm=ADMIN, username=ADMIN, blacklist=False,
    )

    assert recomputed == [{anime.id}]


async def test_removing_the_last_media_skips_the_recompute(db_session, monkeypatch):
    """An emptied anime takes every `user_visible_media` row with it through the
    cascade, so there is nothing left to recompute — the same reason
    `_remove_hentai_anime` skips it. Asserted so the guard can't quietly become an
    unconditional call that recomputes an anime that no longer exists.
    """
    from app.services import delete_candidate_service

    called: list[set[int]] = []

    async def _spy(_db, anime_ids):
        called.append(set(anime_ids))

    monkeypatch.setattr(
        delete_candidate_service, "refresh_spoiler_cache_for_anime_ids", _spy
    )

    anime = await _make_anime_with_media(db_session, mal_base=971500, count=1)
    media = (await _media_for(db_session, anime.id))[0]
    candidate = await _candidate_for(db_session, media)
    await remove(
        db_session, candidate.uuid,
        confirm=ADMIN, username=ADMIN, blacklist=False,
    )

    assert called == []
