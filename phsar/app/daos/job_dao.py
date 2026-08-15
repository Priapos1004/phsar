from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Text, case, cast, func, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.core.job_versions import LIST_OMITTED_SUMMARY_KEYS
from app.daos.base_dao import BaseDAO, recency_order
from app.models.job import Job, JobKind, JobStatus

# `result_summary` with the Jobs Log's detail-only keys removed. Which keys
# and why is in `core/job_versions.py`; applied to every row, since
# `jsonb - text[]` is a no-op for keys a row doesn't carry and NULL minus
# an array is NULL.
#
# What this does and does not save: Postgres still detoasts and decompresses
# the whole column to build the trimmed copy — `jsonb - text[]` needs a
# materialised value, and there is no partial detoast for jsonb the way there
# is for text. What it removes is everything past the socket, which is the
# larger half and the half that repeats: the driver's JSON parse, the
# validate/dump/rebuild walk in `admin_service`, re-serialisation, gzip and
# wire bytes — all of it on a 3s poll. Removing the DB-side read too would
# mean not storing the arrays on the listed row at all (a sidecar), which is
# a bigger change than it is worth until profiling says otherwise.
#
# `cast` because `-` on jsonb needs a text[] on the right; without it the
# array literal comes through untyped and Postgres can't resolve the
# operator. `return_type` keeps the result a parsed dict rather than
# SQLAlchemy's NullType default.
_LIST_SUMMARY_EXPR = Job.result_summary.op("-", return_type=JSONB)(
    cast(array(LIST_OMITTED_SUMMARY_KEYS), ARRAY(Text)),
)


class JobDAO(BaseDAO[Job]):
    @staticmethod
    def scrape_query_expr():
        """The normalized scrape-query expression the dedup lookup filters on.

        Named so `ix_jobs_scrape_query` (declared in `models/job.py` as raw SQL in
        Postgres's own normalized spelling, to keep `alembic check` quiet) has an
        identifiable counterpart. The two must stay the same expression to
        Postgres or the index silently stops being used —
        `test_scrape_dedup_predicate_can_use_its_index` is the guard.
        """
        return func.lower(func.trim(Job.payload["query"].astext))

    # Eager-load options the admin Jobs-Log surfaces need so the response
    # builder can read `requested_by_username` and `parent_job_uuid`
    # without a lazy-raise fault. Shared between the list endpoint and
    # the single-row detail fetch.
    # `parent` is narrowed to its uuid because that is the only field any
    # caller reads off it (`_job_to_admin_response`). Without the narrowing a
    # parent's own full result_summary rides along on every child row of an
    # expanded sweep — the same waste the list projection exists to remove.
    _ADMIN_LOAD_OPTIONS = (
        selectinload(Job.requested_by),
        selectinload(Job.parent).load_only(Job.uuid, raiseload=True),
    )

    def __init__(self):
        super().__init__(Job)

    async def get_by_uuid(self, db: AsyncSession, uuid: UUID) -> Job | None:
        return await self.get_by_field(db, uuid=uuid)

    async def get_by_uuid_with_relations(
        self, db: AsyncSession, uuid: UUID,
    ) -> Job | None:
        """Same as get_by_uuid but eager-loads requested_by + parent so
        the admin detail builder can read both without a lazy-raise
        fault. Worth its own method because the bell's /jobs/{uuid} path
        deliberately stays lighter.

        `populate_existing` because this is the endpoint that must return
        the summary WHOLE: if `list_admin_paginated` has already run in
        this session, the identity map holds that row with a projected
        summary, and the default behaviour would hand it back instead of
        the columns just fetched."""
        stmt = (
            select(Job)
            .where(Job.uuid == uuid)
            .options(*self._ADMIN_LOAD_OPTIONS)
            .execution_options(populate_existing=True)
        )
        return (await db.execute(stmt)).scalars().first()

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

    # "Active" = not yet terminal. Defined once so the two count methods below
    # can't drift if a third status ever counts as in-flight.
    _ACTIVE_STATUSES = (JobStatus.queued, JobStatus.running)

    async def count_active_for_user(self, db: AsyncSession, user_id: int) -> int:
        """Counts queued + running jobs for a user, used to enforce the
        per-user submission cap before enqueueing."""
        stmt = (
            select(func.count(Job.id))
            .where(Job.requested_by_user_id == user_id)
            .where(Job.status.in_(self._ACTIVE_STATUSES))
        )
        return (await db.execute(stmt)).scalar_one()

    async def count_active_by_kind(self, db: AsyncSession, kind: JobKind) -> int:
        """Counts queued + running jobs of one kind, regardless of requester.

        The kind-scoped sibling of `count_active_for_user` — used by the startup
        backup self-heal to avoid stacking a second dump when a restart lands
        while one is still queued or running (system jobs have no user to scope
        by, so the per-user cap doesn't cover them)."""
        stmt = (
            select(func.count(Job.id))
            .where(Job.kind == kind)
            .where(Job.status.in_(self._ACTIVE_STATUSES))
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
        without a client-side join).

        **The returned rows carry a projected `result_summary`** (see
        `_LIST_SUMMARY_EXPR`), so they are for reading into a response and
        nothing else — writing one back would persist the truncated summary,
        and a caller that needs the whole thing wants
        `get_by_uuid_with_relations`, which the detail endpoint uses.

        For the same reason this must stay the only query in its session
        that touches these rows: the projected value is written onto the
        entity as if loaded, so it would overwrite a fully-loaded instance
        already in the identity map."""
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

        page_stmt = select(Job, _LIST_SUMMARY_EXPR.label("list_summary"))
        if filters:
            page_stmt = page_stmt.where(*filters)
        page_stmt = (
            # Paginated, and a seasonal sweep bulk-inserts hundreds of children in
            # one transaction — so they all share a created_at and the PK tiebreak
            # is what stops a row appearing on two pages. See recency_order.
            page_stmt.order_by(*recency_order(Job, "created_at"))
            .limit(limit)
            .offset(offset)
            .options(
                *self._ADMIN_LOAD_OPTIONS,
                # Keep the raw column out of the SELECT entirely — the whole
                # point is not to read it. raiseload so a future path that
                # skips the set_committed_value below faults loudly instead of
                # quietly emitting one lazy load per row.
                defer(Job.result_summary, raiseload=True),
            )
        )
        items: list[Job] = []
        for job, list_summary in (await db.execute(page_stmt)).all():
            # Populate the projected value as if it had been loaded, so the
            # response builder reads `job.result_summary` unchanged and keeps
            # its "no field list to keep in sync" property. set_committed_value
            # (not plain assignment) leaves the instance clean — an assignment
            # would mark it dirty and risk flushing the truncated summary.
            set_committed_value(job, "result_summary", list_summary)
            items.append(job)
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
            .order_by(status_priority.asc(), *recency_order(Job, "created_at"))
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
        result_summary: dict | None = None,
    ) -> None:
        job.status = JobStatus.failed
        job.finished_at = datetime.now(timezone.utc)
        job.error_message = error_message[:2000]
        # Stash retryable + error_category in result_summary so the bell
        # can read them without needing separate columns. retryable
        # hides the retry button when False; error_category lets the
        # bell render friendly copy ("MAL is temporarily unavailable")
        # instead of the raw upstream message for known failure modes.
        # `result_summary` seeds the base dict when the failure carried one
        # (a mid-run abort's partial stats — mirrors mark_succeeded); else
        # merge onto whatever the row already had.
        base = result_summary if result_summary is not None else job.result_summary
        existing = dict(base or {})
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
            .where(self.scrape_query_expr() == normalized)
            .order_by(*recency_order(Job, "created_at"))
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
