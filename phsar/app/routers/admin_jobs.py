"""Cron-authed scheduler endpoints (sweeps, the recommender's eval, auto-backup).

Every endpoint here shares `JOBS_CRON_TOKEN` via `require_jobs_cron_token` and is
mounted under `/admin` by the parent admin router. They sit on a
separate router (no router-level admin dep) so the cron token is the only
auth they require — the JWT admin chain doesn't apply to machine-only
endpoints.

`_enqueue_scheduled_sweep` is local to this module; the backup enqueue path
lives in `backup_service` (three callers now — the manual endpoint in
`admin.py`, the cron endpoints here, and the startup self-heal), which is the
right layer for it since routers depend on services and not the reverse.
"""

import calendar
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_jobs_cron_token
from app.core.maintenance import set_scheduled_at
from app.exceptions import IncompleteSeasonTargetError
from app.models.job import JobKind
from app.models.media import SeasonType
from app.schemas import admin_schema, backup_schema
from app.services import galaxy_service
from app.services.backup_service import enqueue_backup_job
from app.services.job_worker import enqueue

router = APIRouter()


async def _enqueue_scheduled_sweep(
    db: AsyncSession, kind: JobKind, delay_minutes: int, payload: dict | None = None,
) -> admin_schema.ScheduledSweepResponse:
    """Shared enqueue path for the cron-authed sweep schedulers.

    Set the banner timestamp *after* the commit so a failed insert
    doesn't leave a phantom countdown on the frontend. notify() is
    harmless even when not_before_at is in the future: the worker
    re-checks not_before_at on wake and sleeps if the job isn't due
    yet (the 60s wakeup fallback would catch it anyway)."""
    not_before = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    job = await enqueue(db, kind, payload=payload or {}, not_before_at=not_before)
    set_scheduled_at(not_before)
    return admin_schema.ScheduledSweepResponse(job_uuid=job.job_uuid, scheduled_at=not_before)


# `delay_minutes` upper bound is 24h — anything longer is almost certainly
# a typo, and without the cap a misconfigured cron could pass an enormous
# int and blow up timedelta() with OverflowError → 500.
@router.post(
    "/jobs/schedule-sweep",
    response_model=admin_schema.ScheduledSweepResponse,
    dependencies=[Depends(require_jobs_cron_token)],
)
async def schedule_sweep(
    delay_minutes: int = Query(20, ge=0, le=1440),
    db: AsyncSession = Depends(get_db),
):
    return await _enqueue_scheduled_sweep(db, JobKind.update_sweep, delay_minutes)


# Same cron-auth pattern as schedule-sweep; the dispatcher is thin (one MAL
# paginate + N row inserts) so the maintenance window is brief. Child
# user_scrapes run afterwards while the site is live.
#
# `season` + `year` target a chosen season for a manual backfill; without them the
# dispatcher reads the clock at run time, which is what the cron path wants. The
# payload stores MAL's lowercase spelling, the one `fetch_season` takes. 1917 is
# the earliest season MAL lists.
@router.post(
    "/jobs/schedule-seasonal",
    response_model=admin_schema.ScheduledSweepResponse,
    dependencies=[Depends(require_jobs_cron_token)],
)
async def schedule_seasonal(
    delay_minutes: int = Query(20, ge=0, le=1440),
    season: SeasonType | None = None,
    year: int | None = Query(None, ge=1917),
    db: AsyncSession = Depends(get_db),
):
    if (season is None) != (year is None):
        raise IncompleteSeasonTargetError()
    payload = {"year": year, "season": season.value.lower()} if season is not None else None
    return await _enqueue_scheduled_sweep(
        db, JobKind.seasonal_sweep, delay_minutes, payload,
    )


# The next-season sweep — same dispatcher as seasonal, targeting next season so
# users can pre-add next-quarter shows to their watchlists. Kept as a standalone
# endpoint (mirrors schedule-seasonal) for ad-hoc triggers + end-to-end testing;
# schedule-nightly fires it automatically on the right days.
@router.post(
    "/jobs/schedule-upcoming",
    response_model=admin_schema.ScheduledSweepResponse,
    dependencies=[Depends(require_jobs_cron_token)],
)
async def schedule_upcoming(
    delay_minutes: int = Query(20, ge=0, le=1440),
    db: AsyncSession = Depends(get_db),
):
    return await _enqueue_scheduled_sweep(db, JobKind.upcoming_sweep, delay_minutes)


# Combined daily cron entry — one Coolify scheduled task hits this and the
# endpoint decides which jobs to enqueue. Routes through the same per-kind
# helpers as the individual schedulers, so each job is enqueued one way.
@router.post(
    "/jobs/schedule-nightly",
    response_model=admin_schema.NightlyScheduleResponse,
    dependencies=[Depends(require_jobs_cron_token)],
)
async def schedule_nightly(
    delay_minutes: int = Query(20, ge=0, le=1440),
    db: AsyncSession = Depends(get_db),
):
    """The night's jobs: what runs when, and why in this order, is
    docs/features/jobs.md, "Scheduling"."""
    now = datetime.now(timezone.utc)
    backup = await enqueue_backup_job(
        db, backup_schema.BackupSource.cron, label=None, requested_by_user_id=None,
    )
    sweep = await _enqueue_scheduled_sweep(db, JobKind.update_sweep, delay_minutes)
    seasonal: admin_schema.ScheduledSweepResponse | None = None
    if now.weekday() == calendar.SUNDAY:
        seasonal = await _enqueue_scheduled_sweep(
            db, JobKind.seasonal_sweep, delay_minutes,
        )
    upcoming: admin_schema.ScheduledSweepResponse | None = None
    if now.weekday() == calendar.WEDNESDAY and now.month % 3 == 0:
        upcoming = await _enqueue_scheduled_sweep(
            db, JobKind.upcoming_sweep, delay_minutes,
        )

    galaxy = await galaxy_service.ensure_map(db, now=now, not_before_at=sweep.scheduled_at)
    evaluation: admin_schema.JobEnqueuedResponse | None = None
    if now.weekday() == calendar.MONDAY:
        evaluation = await enqueue(db, JobKind.recommender_eval, not_before_at=sweep.scheduled_at)

    return admin_schema.NightlyScheduleResponse(
        backup_uuid=backup.job_uuid,
        update_sweep_uuid=sweep.job_uuid,
        seasonal_sweep_uuid=seasonal.job_uuid if seasonal is not None else None,
        upcoming_sweep_uuid=upcoming.job_uuid if upcoming is not None else None,
        galaxy_rebuild_uuid=galaxy.job_uuid if galaxy is not None else None,
        recommender_eval_uuid=evaluation.job_uuid if evaluation is not None else None,
        scheduled_at=sweep.scheduled_at,
    )


# The weekly eval on demand. No banner: it writes only its own table, so it needs no maintenance
# window and runs at once by default.
@router.post(
    "/jobs/schedule-recommender-eval",
    response_model=admin_schema.JobEnqueuedResponse,
    dependencies=[Depends(require_jobs_cron_token)],
)
async def schedule_recommender_eval(
    delay_minutes: int = Query(0, ge=0, le=1440),
    db: AsyncSession = Depends(get_db),
):
    not_before = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    return await enqueue(db, JobKind.recommender_eval, not_before_at=not_before)


# Cron-authed endpoint — kept on this sub-router so it doesn't inherit the
# JWT admin dep that the backups CRUD sub-router carries. Auth shares
# JOBS_CRON_TOKEN with the other cron-authed endpoints so the deployment
# only carries one bearer secret.
@router.post(
    "/backups/auto",
    response_model=admin_schema.JobEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_jobs_cron_token)],
)
async def auto_backup(db: AsyncSession = Depends(get_db)):
    """Cron-triggered backup. Enqueues a `backup` job tagged `cron`; the
    dispatcher creates the dump and then applies retention so the
    14-daily/8-Sunday/most-recent-known-good contract holds without an
    extra cron-side step."""
    return await enqueue_backup_job(
        db, backup_schema.BackupSource.cron, label=None, requested_by_user_id=None,
    )
