"""Cron-authed scheduler endpoints (sweeps + auto-backup).

All four endpoints share `JOBS_CRON_TOKEN` via `require_jobs_cron_token`
and are mounted under `/admin` by the parent admin router. They sit on a
separate router (no router-level admin dep) so the cron token is the only
auth they require — the JWT admin chain doesn't apply to machine-only
endpoints.

The two helpers (`_enqueue_scheduled_sweep`, `enqueue_backup_job`) are
exported because `admin.py`'s manual-backup endpoint shares the backup
enqueue path.
"""

import calendar
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_jobs_cron_token
from app.core.maintenance import set_scheduled_at
from app.models.job import Job, JobKind, JobStatus
from app.schemas import admin_schema, backup_schema
from app.services.job_worker import job_worker

router = APIRouter()


async def _enqueue_scheduled_sweep(
    db: AsyncSession, kind: JobKind, delay_minutes: int,
) -> admin_schema.ScheduledSweepResponse:
    """Shared enqueue path for the two cron-authed sweep schedulers.

    Set the banner timestamp *after* the commit so a failed insert
    doesn't leave a phantom countdown on the frontend. notify() is
    harmless even when not_before_at is in the future: the worker
    re-checks not_before_at on wake and sleeps if the job isn't due
    yet (the 60s wakeup fallback would catch it anyway)."""
    not_before = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    job = Job(
        kind=kind,
        status=JobStatus.queued,
        payload={},
        not_before_at=not_before,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    set_scheduled_at(not_before)
    job_worker.notify()
    return admin_schema.ScheduledSweepResponse(
        job_uuid=job.uuid, scheduled_at=not_before,
    )


async def enqueue_backup_job(
    db: AsyncSession,
    source: backup_schema.BackupSource,
    label: str | None,
    requested_by_user_id: int | None,
) -> admin_schema.JobEnqueuedResponse:
    """Shared enqueue path for the manual + cron backup endpoints.

    Backup work now flows through the JobWorker so admins don't wait
    minutes for pg_dump and the cron path gets FIFO sequencing + crash
    recovery for free. The dispatcher (`backup_dispatcher`) applies
    retention after every job — manual and cron share the same
    14-recent + 8-Sunday + 1-known-good pool, so a manual-only install
    doesn't accumulate dumps indefinitely.

    Manual backups attribute to the admin user so the row surfaces in
    *their* bell only — multi-admin deployments don't get cross-admin
    bell clutter. Cron leaves `requested_by_user_id=None` (system job,
    same pattern as sweeps), invisible to every user's bell — the dump
    list is the audit log for those.
    """
    payload: dict[str, Any] = {"source": source.value}
    if label:
        payload["label"] = label
    job = Job(
        kind=JobKind.backup,
        status=JobStatus.queued,
        requested_by_user_id=requested_by_user_id,
        payload=payload,
    )
    db.add(job)
    await db.commit()
    job_worker.notify()
    return admin_schema.JobEnqueuedResponse(job_uuid=job.uuid)


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
@router.post(
    "/jobs/schedule-seasonal",
    response_model=admin_schema.ScheduledSweepResponse,
    dependencies=[Depends(require_jobs_cron_token)],
)
async def schedule_seasonal(
    delay_minutes: int = Query(20, ge=0, le=1440),
    db: AsyncSession = Depends(get_db),
):
    return await _enqueue_scheduled_sweep(db, JobKind.seasonal_sweep, delay_minutes)


# Combined daily cron entry — one Coolify scheduled task hits this and the
# endpoint decides which jobs to enqueue. Routes through the same per-kind
# helpers as the individual schedulers so the post-commit ceremony
# (set_scheduled_at + job_worker.notify) is centralized.
@router.post(
    "/jobs/schedule-nightly",
    response_model=admin_schema.NightlyScheduleResponse,
    dependencies=[Depends(require_jobs_cron_token)],
)
async def schedule_nightly(
    delay_minutes: int = Query(20, ge=0, le=1440),
    db: AsyncSession = Depends(get_db),
):
    """Backup (immediate) + update_sweep (delayed) + seasonal_sweep
    (delayed, Sundays UTC only). The seasonal piggybacks on the same
    `not_before_at` as update_sweep so the weekly catalog pickup shares
    the daily maintenance window instead of opening its own."""
    backup = await enqueue_backup_job(
        db, backup_schema.BackupSource.cron, label=None, requested_by_user_id=None,
    )
    sweep = await _enqueue_scheduled_sweep(db, JobKind.update_sweep, delay_minutes)
    seasonal: admin_schema.ScheduledSweepResponse | None = None
    if datetime.now(timezone.utc).weekday() == calendar.SUNDAY:
        seasonal = await _enqueue_scheduled_sweep(
            db, JobKind.seasonal_sweep, delay_minutes,
        )

    return admin_schema.NightlyScheduleResponse(
        backup_uuid=backup.job_uuid,
        update_sweep_uuid=sweep.job_uuid,
        seasonal_sweep_uuid=seasonal.job_uuid if seasonal is not None else None,
        scheduled_at=sweep.scheduled_at,
    )


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
