from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.job import Job, JobKind, JobStatus


class JobDAO(BaseDAO[Job]):
    def __init__(self):
        super().__init__(Job)

    async def get_by_uuid(self, db: AsyncSession, uuid: UUID) -> Job | None:
        return await self.get_by_field(db, uuid=uuid)

    async def claim_next_queued(self, db: AsyncSession) -> Job | None:
        """Atomically grab the oldest runnable queued job and mark it running.

        Uses SKIP LOCKED so a future multi-worker rollout doesn't have us all
        contending on the same row. Honors not_before_at for delayed jobs
        (announce-then-run pattern). Caller commits the transaction.
        """
        stmt = (
            select(Job)
            .where(Job.status == JobStatus.queued)
            .where(or_(Job.not_before_at.is_(None), Job.not_before_at <= func.now()))
            .order_by(Job.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = (await db.execute(stmt)).scalars().first()
        if job is None:
            return None
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        await db.flush()
        return job

    async def count_active_for_user(self, db: AsyncSession, user_id: int) -> int:
        """Counts queued + running jobs for a user, used to enforce the
        per-user submission cap before enqueueing."""
        stmt = (
            select(func.count(Job.id))
            .where(Job.requested_by_user_id == user_id)
            .where(Job.status.in_((JobStatus.queued, JobStatus.running)))
        )
        return (await db.execute(stmt)).scalar_one()

    async def count_user_scrapes_in_window(
        self, db: AsyncSession, user_id: int, hours: int = 24
    ) -> int:
        """Counts user_scrape jobs by a user within the trailing window,
        used to enforce the daily submission cap. Counts every status —
        a failed scrape still hit MAL, so it shouldn't free up a slot.

        Backed by ix_jobs_user_scrape_recent (partial composite on
        user + created_at DESC, kind='user_scrape') so the lookup stays
        O(in-window-rows) even for users with thousands of historical
        scrapes."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = (
            select(func.count(Job.id))
            .where(Job.requested_by_user_id == user_id)
            .where(Job.kind == JobKind.user_scrape)
            .where(Job.created_at >= cutoff)
        )
        return (await db.execute(stmt)).scalar_one()

    async def list_admin_paginated(
        self,
        db: AsyncSession,
        *,
        status: JobStatus | None = None,
        kind: JobKind | None = None,
        user_id: int | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        parent_job_id: int | None = None,
        roots_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Job], int]:
        """Admin Jobs Log: paginated listing across every user. Returns
        the page rows + the matching-total count. Newest-first by
        created_at so the most recent activity surfaces immediately.

        When `parent_job_id` is set, returns children of that parent;
        ignores `roots_only`. When `roots_only` is True (default), hides
        rows that have a parent so the admin's main list doesn't drown
        in seasonal-sweep children — expand a parent row to see them.

        Each Job eager-loads `requested_by` (for username flattening)
        and `parent` (so the row's response can carry the parent's uuid
        without a client-side join)."""
        filters = []
        if status is not None:
            filters.append(Job.status == status)
        if kind is not None:
            filters.append(Job.kind == kind)
        if user_id is not None:
            filters.append(Job.requested_by_user_id == user_id)
        if created_after is not None:
            filters.append(Job.created_at >= created_after)
        if created_before is not None:
            filters.append(Job.created_at <= created_before)
        if parent_job_id is not None:
            filters.append(Job.parent_job_id == parent_job_id)
        elif roots_only:
            filters.append(Job.parent_job_id.is_(None))

        total_stmt = select(func.count(Job.id))
        if filters:
            total_stmt = total_stmt.where(*filters)
        total = (await db.execute(total_stmt)).scalar_one()

        page_stmt = select(Job)
        if filters:
            page_stmt = page_stmt.where(*filters)
        page_stmt = (
            page_stmt.order_by(Job.created_at.desc())
            .limit(limit)
            .offset(offset)
            .options(selectinload(Job.requested_by), selectinload(Job.parent))
        )
        items = list((await db.execute(page_stmt)).scalars().all())
        return items, total

    async def list_for_user(self, db: AsyncSession, user_id: int, limit: int = 25) -> list[Job]:
        """Recent jobs for the navbar bell. Active first (running, then queued),
        then finished by recency. The bell renders the response order directly,
        so ordering only by created_at would surface newer queued jobs above
        the currently running one."""
        status_priority = case(
            (Job.status == JobStatus.running, 0),
            (Job.status == JobStatus.queued, 1),
            else_=2,
        )
        stmt = (
            select(Job)
            .where(Job.requested_by_user_id == user_id)
            .order_by(status_priority.asc(), Job.created_at.desc())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def mark_progress(
        self,
        db: AsyncSession,
        job: Job,
        stage: str | None = None,
        items_done: int | None = None,
        items_total: int | None = None,
    ) -> None:
        """Update only the fields the caller specifies. Used by the dispatcher's
        ProgressReporter for mid-flight updates that bypass the main work tx."""
        if stage is not None:
            job.stage = stage
        if items_done is not None:
            job.items_done = items_done
        if items_total is not None:
            job.items_total = items_total
        await db.flush()

    async def mark_succeeded(
        self,
        db: AsyncSession,
        job: Job,
        result_summary: dict | None = None,
    ) -> None:
        job.status = JobStatus.succeeded
        job.finished_at = datetime.now(timezone.utc)
        if result_summary is not None:
            job.result_summary = result_summary
        await db.flush()

    async def mark_failed(
        self,
        db: AsyncSession,
        job: Job,
        error_message: str,
        retryable: bool = True,
        error_category: str | None = None,
    ) -> None:
        job.status = JobStatus.failed
        job.finished_at = datetime.now(timezone.utc)
        job.error_message = error_message[:2000]
        # Stash retryable + error_category in result_summary so the bell
        # can read them without needing separate columns. retryable
        # hides the retry button when False; error_category lets the
        # bell render friendly copy ("MAL is temporarily unavailable")
        # instead of the raw upstream message for known failure modes.
        existing = dict(job.result_summary or {})
        existing["retryable"] = retryable
        if error_category is not None:
            existing["error_category"] = error_category
        job.result_summary = existing
        await db.flush()

    async def reap_orphans(self, db: AsyncSession) -> int:
        """Mark every running job as failed. Run at app startup so a job that
        was mid-flight when the process died doesn't sit in `running` forever.
        Caller commits the transaction. Returns number of rows updated."""
        stmt = (
            update(Job)
            .where(Job.status == JobStatus.running)
            .values(
                status=JobStatus.failed,
                error_message="App restarted mid-job",
                finished_at=datetime.now(timezone.utc),
            )
        )
        result = await db.execute(stmt)
        return result.rowcount or 0

    async def find_recent_scrape_for_query(
        self,
        db: AsyncSession,
        query: str,
        hours: int,
    ) -> Job | None:
        """Most-recent user_scrape job matching this query (case-insensitive,
        trim-normalized) within the lookback window. Failed jobs are
        intentionally excluded so a transient MAL outage doesn't lock the
        query out for 3 days.
        """
        normalized = query.strip().lower()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = (
            select(Job)
            .where(Job.kind == JobKind.user_scrape)
            .where(
                Job.status.in_(
                    (JobStatus.queued, JobStatus.running, JobStatus.succeeded)
                )
            )
            .where(Job.created_at >= cutoff)
            .where(
                func.lower(func.trim(Job.payload["query"].astext)) == normalized
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_with_user(self, db: AsyncSession, uuid: UUID) -> Job | None:
        stmt = (
            select(Job)
            .where(Job.uuid == uuid)
            .options(selectinload(Job.requested_by))
        )
        return (await db.execute(stmt)).scalars().first()
