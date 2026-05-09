from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.job import Job, JobStatus


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

    async def list_for_user(self, db: AsyncSession, user_id: int, limit: int = 25) -> list[Job]:
        """Recent jobs for the navbar bell. Active first, then most-recent finished."""
        stmt = (
            select(Job)
            .where(Job.requested_by_user_id == user_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars().all())

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
    ) -> None:
        job.status = JobStatus.failed
        job.finished_at = datetime.now(timezone.utc)
        job.error_message = error_message[:2000]
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

    async def get_with_user(self, db: AsyncSession, uuid: UUID) -> Job | None:
        stmt = (
            select(Job)
            .where(Job.uuid == uuid)
            .options(selectinload(Job.requested_by))
        )
        return (await db.execute(stmt)).scalars().first()
