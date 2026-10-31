"""The galaxy rebuild job, with the fit itself stubbed: the swap, names carried onto the
new map, a failed fit leaving the live map alone, when a rebuild is due — and one real
child process, since the fit's isolation rests on it."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select

from app.daos.job_dao import JobDAO
from app.models.anime import Anime
from app.models.galaxy import GalaxyFit, GalaxyGroup, GalaxyStar
from app.models.job import Job, JobKind
from app.services import galaxy_compute, galaxy_service
from app.services.anime_search_service import anime_title_texts
from app.services.galaxy_dispatcher import galaxy_rebuild_dispatcher
from app.services.vector_embedding_service import MODEL_NAME, create_anime_embedding
from tests._helpers import NoopProgressReporter, fake_job


def _fake_fit(anime, _media, _previous):
    """One sector holding one region and every anime — enough for the swap to write."""
    ids = [a.anime_id for a in anime]
    return {
        "stars": [
            {"anime_id": aid, "x": 0.0, "y": 0.0, "z10": [0.0] * 10, "sector": 0, "region": 0,
             "between": False, "trained": True, "features": [1.0, 0.0]}
            for aid in ids
        ],
        "groups": [
            {"level": "sector", "number": 0, "parent": None, "auto_name": "Auto sector", "x": 0.0, "y": 0.0,
             "trained_members": ids},
            {"level": "region", "number": 0, "parent": 0, "auto_name": "Auto region", "x": 0.0, "y": 0.0,
             "trained_members": ids},
        ],
        "blob": b"models",
        "pair_cosine_percentiles": [0.0] * 101,
        "summary": {"trained": len(ids), "predicted": 0, "sectors": 1, "regions": 1, "between_share": 0.0},
    }


@pytest.fixture
def stub_fit(monkeypatch):
    monkeypatch.setattr("app.services.galaxy_dispatcher.ProgressReporter", NoopProgressReporter)

    async def in_process(fn, *args):
        assert fn is galaxy_compute.fit
        return _fake_fit(*args)

    monkeypatch.setattr(galaxy_service, "run_in_child", in_process)


@pytest.fixture
async def catalogue(db_session):
    """An anime with an embedding, so the fit has something to load on an empty database."""
    anime = Anime(mal_id=99101, title="Galaxy Fixture", description="A fixture for the map.")
    db_session.add(anime)
    await db_session.flush()
    await create_anime_embedding(
        db_session, anime_id=anime.id, title_texts=anime_title_texts(anime), description_text=anime.description,
    )


async def test_a_rebuild_swaps_the_map_and_carries_hand_names(db_session, catalogue, stub_fit):
    await galaxy_rebuild_dispatcher(db_session, fake_job())
    sector = (await db_session.execute(select(GalaxyGroup).where(GalaxyGroup.parent_id.is_(None)))).scalar_one()
    await galaxy_service.rename_group(db_session, sector.uuid, "Isekai Sprawl")

    summary = await galaxy_rebuild_dispatcher(db_session, fake_job())

    assert (await db_session.execute(select(func.count()).select_from(GalaxyFit))).scalar_one() == 1
    names = dict((await db_session.execute(select(GalaxyGroup.auto_name, GalaxyGroup.name))).all())
    assert names == {"Auto sector": "Isekai Sprawl", "Auto region": None}
    assert summary["names_carried"] == 1
    stars = (await db_session.execute(select(func.count()).select_from(GalaxyStar))).scalar_one()
    assert stars == (await db_session.execute(
        select(func.count()).select_from(Anime).where(Anime.anime_search.has())
    )).scalar_one()


async def test_a_failed_fit_keeps_the_live_map(db_session, catalogue, stub_fit, monkeypatch):
    await galaxy_rebuild_dispatcher(db_session, fake_job())
    live = (await db_session.execute(select(GalaxyFit.id))).scalar_one()

    async def fails(*_args):
        raise RuntimeError("fit died")

    monkeypatch.setattr(galaxy_service, "run_in_child", fails)
    with pytest.raises(RuntimeError, match="fit died"):
        await galaxy_rebuild_dispatcher(db_session, fake_job())
    assert (await db_session.execute(select(GalaxyFit.id))).scalar_one() == live


# This quarter's refit date is 2026-04-15.
NOW = datetime(2026, 5, 2, tzinfo=timezone.utc)


async def _waiting_rebuilds(db_session) -> int:
    return await JobDAO().count_active_by_kind(db_session, JobKind.galaxy_rebuild)


@pytest.mark.parametrize(("fitted_at", "model", "enqueued"), [
    (None, None, 1),  # no map: a first deploy or a fresh database
    (NOW - timedelta(days=1), MODEL_NAME, 0),
    (datetime(2026, 4, 14, tzinfo=timezone.utc), MODEL_NAME, 1),  # before this quarter's refit date
    (NOW - timedelta(days=1), "another-model", 1),  # the boot re-embedded the vectors under it
])
async def test_a_rebuild_is_enqueued_when_the_map_is_due(
    db_session, catalogue, monkeypatch, fitted_at, model, enqueued,
):
    monkeypatch.setattr(galaxy_compute, "MIN_CATALOGUE", 1)
    await db_session.execute(delete(Job).where(Job.kind == JobKind.galaxy_rebuild))
    await db_session.execute(delete(GalaxyFit))
    if fitted_at is not None:
        db_session.add(GalaxyFit(
            models=b"", params={"built_from": {**galaxy_service.built_from(), "model": model}},
            created_at=fitted_at,
        ))
        await db_session.flush()

    await galaxy_service.ensure_map(db_session, now=NOW)
    assert await _waiting_rebuilds(db_session) == enqueued
    # Asked again while that one waits (the next boot, the next night), it does not stack.
    await galaxy_service.ensure_map(db_session, now=NOW)
    assert await _waiting_rebuilds(db_session) == enqueued


async def test_no_rebuild_on_a_catalogue_too_small_to_fit(db_session, catalogue, monkeypatch):
    await db_session.execute(delete(Job).where(Job.kind == JobKind.galaxy_rebuild))
    await db_session.execute(delete(GalaxyFit))
    size = await galaxy_service.galaxy_dao.catalogue_size(db_session)
    monkeypatch.setattr(galaxy_compute, "MIN_CATALOGUE", size + 1)
    assert await galaxy_service.ensure_map(db_session, now=NOW) is None
    assert await _waiting_rebuilds(db_session) == 0


@pytest.mark.parametrize(("now", "refit"), [
    (datetime(2026, 1, 10, tzinfo=timezone.utc), datetime(2025, 10, 15, tzinfo=timezone.utc)),
    (datetime(2026, 1, 15, tzinfo=timezone.utc), datetime(2026, 1, 15, tzinfo=timezone.utc)),
    (datetime(2026, 3, 31, 23, tzinfo=timezone.utc), datetime(2026, 1, 15, tzinfo=timezone.utc)),
    (datetime(2026, 4, 14, 23, tzinfo=timezone.utc), datetime(2026, 1, 15, tzinfo=timezone.utc)),
    (datetime(2026, 12, 31, tzinfo=timezone.utc), datetime(2026, 10, 15, tzinfo=timezone.utc)),
])
def test_the_refit_date_is_the_latest_quarterly_fifteenth(now, refit):
    assert galaxy_service.refit_date(now) == refit


async def test_compute_runs_in_a_spawned_child():
    """The child imports `galaxy_compute` alone; this fails if the module drags the app
    (or the model) in, or cannot be imported from a fresh interpreter."""
    assert await galaxy_service.run_in_child(galaxy_compute.carry_names, [], []) == {}
