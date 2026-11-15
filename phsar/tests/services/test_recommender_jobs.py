"""The weekly `recommender_eval` job against a real database: what it reads, and what its
verdict writes. The child process is replaced by an in-process call; the measuring itself is
`recommender_eval`'s, tested there."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.job_versions import JOB_KIND_VERSIONS, make_job
from app.daos.job_dao import JobDAO
from app.models.anime import Anime
from app.models.galaxy import GalaxyFit, GalaxyGroup, GalaxyStar
from app.models.job import Job, JobKind, JobStatus
from app.models.media import Media
from app.models.ratings import Ratings, WatchStatus
from app.models.recommendation import (
    RecommendationExposure,
    RecommendationKind,
    RecommenderFit,
)
from app.models.user_settings import UserSettings
from app.models.watch_event import WatchEvent
from app.services import child_process, recommender_eval, recommender_service
from app.services import recommender_compute as rc
from app.services.recommender_dispatcher import recommender_eval_dispatcher
from tests import ON_DEV_DB
from tests._helpers import NoopProgressReporter, fake_job, make_user, media_kwargs


@pytest.fixture
def in_process(monkeypatch):
    monkeypatch.setattr("app.services.recommender_dispatcher.ProgressReporter", NoopProgressReporter)

    async def run(fn, *args):
        return fn(*args)

    monkeypatch.setattr(child_process, "run_in_child", run)


@pytest.mark.skipif(ON_DEV_DB, reason="replays every user of the dev database")
async def test_the_eval_measures_a_seeded_history_and_waits_for_the_log(db_session, in_process):
    """A user who watched eight anime on eight days, rewatched the first on day 11 and was
    shown the last on day 6: five decisions after the first three picks, one complete rewatch,
    one stretch watched. The watchlist has no log, so the job only measures."""
    db = db_session
    user = await make_user(db, "eval-user")
    db.add(UserSettings(user_id=user.id))
    anime = [Anime(mal_id=-93000 - i, title=f"A-9300{i}-eval") for i in range(8)]
    db.add_all(anime)
    await db.flush()
    media = [Media(**media_kwargs(a.id, a.mal_id)) for a in anime]
    fit = GalaxyFit(models=b"", params={})
    db.add_all([*media, fit])
    await db.flush()
    sector = GalaxyGroup(fit_id=fit.id, number=0, auto_name="Sector", x=0.0, y=0.0)
    db.add(sector)
    await db.flush()
    start = datetime(2026, 9, 1, tzinfo=UTC)
    for i, (a, m) in enumerate(zip(anime, media, strict=True)):
        at = start + timedelta(days=i)
        db.add_all([
            GalaxyStar(
                anime_id=a.id, sector_id=sector.id, region_id=sector.id, x=0.0, y=0.0, z10=[0.0] * 10,
                features=[float(i), 0.0], uncertainty=0.0, between=False, trained=True,
            ),
            Ratings(user_id=user.id, media_id=m.id, rating=7.0, watch_status=WatchStatus.completed, created_at=at, modified_at=at),
            WatchEvent(user_id=user.id, media_id=m.id, watched_at=at),
        ])
    shown = start + timedelta(days=6, hours=1)
    db.add_all([
        WatchEvent(user_id=user.id, media_id=media[0].id, watched_at=start + timedelta(days=11)),
        RecommendationExposure(
            user_id=user.id, anime_id=anime[7].id, best_rank=1, kind=RecommendationKind.FRESH,
            created_at=shown, modified_at=shown,
        ),
    ])
    await db.flush()

    summary = json.loads(json.dumps(await recommender_eval_dispatcher(db, fake_job())))

    assert summary["verdict"] == "waiting"
    assert summary["log"]["picks"] == 0
    report = summary["report"]
    assert report["decisions"] == {"total": 5}
    assert report["rewatch"]["decisions"] == 1
    assert report["online"]["by_reason"] == {"fresh": {"judged": 1, "watched": 1, "share": 1.0}}
    assert summary["fit"] is None
    assert (await db.execute(select(RecommenderFit))).first() is None


@pytest.fixture
def weekly(monkeypatch, in_process):
    """Sets what the measuring decides: a verdict and the refit's weights."""
    def answer(verdict: str, refit: dict[str, float]):
        summary = {"verdict": verdict, "guards": [], "log": {}, "would_help": [],
                   "report": {"weights": {"live": {}, "refit": refit}}}
        monkeypatch.setattr(recommender_eval, "weekly", lambda *_: summary)

    return answer


async def _fits(db) -> list[RecommenderFit]:
    return list((await db.execute(select(RecommenderFit))).scalars())


async def test_an_applied_refit_is_stored_and_ranks_from_then_on(db_session, weekly):
    """Stored for this code's version and read as the live weights; the same refit applied
    again writes nothing new."""
    await db_session.execute(delete(RecommenderFit))
    refit = {"F5_mal": 1.0, "W_p1": 0.5}
    weekly("applied", refit)

    summary = await recommender_eval_dispatcher(db_session, fake_job())
    (fit,) = await _fits(db_session)
    assert (fit.weights, fit.built_for, summary["fit"]) == (refit, rc.version(), str(fit.uuid))
    assert await recommender_service.live_weights(db_session) == (fit.uuid, refit)

    again = await recommender_eval_dispatcher(db_session, fake_job())
    assert [f.uuid for f in await _fits(db_session)] == [fit.uuid]
    assert again["fit"] == str(fit.uuid)


@pytest.mark.parametrize("verdict", ["held", "waiting"])
async def test_a_refit_held_back_or_waiting_is_not_stored(db_session, weekly, verdict):
    await db_session.execute(delete(RecommenderFit))
    weekly(verdict, {"F5_mal": 1.0})
    summary = await recommender_eval_dispatcher(db_session, fake_job())
    assert await _fits(db_session) == []
    assert summary["fit"] is None
    assert await recommender_service.live_weights(db_session) == (None, rc.WEIGHTS)


async def test_a_fit_for_other_code_ranks_by_the_committed_weights(db_session):
    """A commit that changes the model's constants changes `version()`: the stored fit was
    fitted for other features, so the committed weights rank until the next refit."""
    await db_session.execute(delete(RecommenderFit))
    db_session.add(RecommenderFit(weights={"F5_mal": 1.0}, built_for="an older version"))
    await db_session.flush()
    assert await recommender_service.live_weights(db_session) == (None, rc.WEIGHTS)


async def test_only_runs_in_the_current_summary_shape_are_compared(db_session):
    """A run whose summary has another shape (`JOB_KIND_VERSIONS`) is left out of what the next
    run compares with, however recent: its keys may not be where `weekly` reads them."""
    now = datetime.now(UTC)
    current, reshaped = (
        make_job(JobKind.recommender_eval, status=JobStatus.succeeded, result_summary={"run": "current"}, created_at=now),
        Job(kind=JobKind.recommender_eval, version=JOB_KIND_VERSIONS[JobKind.recommender_eval] + 1,
            status=JobStatus.succeeded, result_summary={"run": "reshaped"}, created_at=now + timedelta(seconds=1)),
    )
    db_session.add_all([current, reshaped])
    await db_session.flush()
    summaries = await JobDAO().latest_summaries(db_session, JobKind.recommender_eval, 5)
    assert {"run": "current"} in summaries and {"run": "reshaped"} not in summaries
