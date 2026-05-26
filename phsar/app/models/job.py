import enum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class JobKind(str, enum.Enum):
    user_scrape = "user_scrape"
    update_sweep = "update_sweep"
    seasonal_sweep = "seasonal_sweep"
    backup = "backup"
    # `restore` rows are inserted synchronously by restore_backup AFTER the
    # operation completes — terminal-state on creation. status=succeeded
    # on pg_restore success; status=failed (with error_message populated)
    # when pg_restore raised. Never inserted at queued/running, never
    # claimed by the worker (no dispatcher registered for this kind), so
    # JobDAO.reap_orphans can't touch them. The row exists purely so the
    # jobs table tells a chronologically complete story of system-mutating
    # operations.
    restore = "restore"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class Job(BaseModel):
    __tablename__ = "jobs"

    kind = Column(Enum(JobKind), nullable=False)
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.queued)

    # Nullable because system-triggered jobs (sweeps) have no requester.
    requested_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Self-referential FK so seasonal_sweep can stamp the parent's id on each
    # user_scrape child it enqueues. Admin Jobs Log collapses children under
    # the parent row. ON DELETE SET NULL keeps the audit history intact if
    # the parent ever gets deleted.
    parent_job_id = Column(
        Integer,
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Per-kind input. user_scrape stores {"query": ..., "mal_id": ...};
    # sweeps may stash their own selection criteria. JSONB keeps the schema
    # one table instead of three near-identical tables.
    payload = Column(JSONB, nullable=False, default=dict)

    # Free-form per-kind label; sweeps and scrapes have disjoint stages.
    stage = Column(String(64), nullable=True)
    # NULL until the first BFS pass returns — the frontend renders an
    # indeterminate spinner while items_total is unknown.
    items_total = Column(Integer, nullable=True)
    items_done = Column(Integer, nullable=False, default=0)

    result_summary = Column(JSONB, nullable=True)
    error_message = Column(String, nullable=True)

    # Worker skips a queued job until now() >= not_before_at. Powers the
    # 20-minute pre-maintenance announcement window.
    not_before_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    requested_by = relationship("Users", lazy="raise")
    parent = relationship("Job", remote_side="Job.id", lazy="raise")

    __table_args__ = (
        # Partial: only queued rows, ordered by created_at. The worker's
        # claim query walks this index in FIFO order; the not_before_at
        # filter is applied as a recheck on the (small) result set. The
        # index excludes finished jobs entirely so it stays tiny regardless
        # of how much history accumulates.
        Index(
            "ix_jobs_queued_by_age",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        # Backs count_active_for_user (per-user submission cap).
        Index("ix_jobs_user_status", "requested_by_user_id", "status"),
        # Backs JobDAO.list_admin_paginated — the Jobs Log tab's default
        # (unfiltered) view does ORDER BY created_at DESC LIMIT 50 plus a
        # matching COUNT. Plain btree — PG scans backward for DESC, no
        # need to pin order.
        Index("ix_jobs_created_at_desc", "created_at"),
        # Backs JobDAO.count_user_scrapes_in_window — the daily-cap
        # check fires on every /jobs/scrape POST. Partial on user_scrape
        # so the index stays small relative to the full jobs history.
        Index(
            "ix_jobs_user_scrape_recent",
            "requested_by_user_id",
            "created_at",
            postgresql_where=text("kind = 'user_scrape'"),
        ),
        # Backs `?parent_uuid=…` lookups on the admin Jobs Log when the
        # admin expands a seasonal_sweep row. Partial — >99% of jobs are
        # root rows with parent_job_id NULL, so the index only covers the
        # small minority where lookups actually fire.
        Index(
            "ix_jobs_parent_job_id",
            "parent_job_id",
            postgresql_where=text("parent_job_id IS NOT NULL"),
        ),
    )


# Expression index — defined at module scope (rather than in __table_args__)
# because the leading column is a JSONB extraction. Backs
# JobDAO.find_recent_scrape_for_query, the dedup check that fires on every
# /jobs/scrape POST.
Index(
    "ix_jobs_scrape_query",
    func.lower(func.trim(Job.payload["query"].astext)),
    Job.created_at.desc(),
    postgresql_where=text("kind = 'user_scrape'"),
)
