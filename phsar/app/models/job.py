import enum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Integer, String, text
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
    )
