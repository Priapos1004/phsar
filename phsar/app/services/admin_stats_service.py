"""Aggregate stats for the admin Overview tab.

Pure SQL counts against the live catalog. No caching — admin-only,
hit rate is low, the queries are cheap. Revisit if any single query
crosses ~10ms in EXPLAIN against a year-old catalog.

Privacy posture: aggregates only. No per-user breakdowns — the Jobs
Log tab surfaces requested_by_user_id where it's needed for debugging,
but the Overview tab stays leaderboard-free.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.merge_candidate_dao import MergeCandidateDAO
from app.daos.split_candidate_dao import SplitCandidateDAO
from app.models.anime import Anime
from app.models.job import Job, JobKind, JobStatus
from app.models.media import Media
from app.models.ratings import Ratings
from app.schemas.admin_schema import (
    ActivityStats,
    AdminOverviewStats,
    CatalogStats,
    CurationPendingCounts,
    JobKindStats,
    JobsStats,
)

merge_candidate_dao = MergeCandidateDAO()
split_candidate_dao = SplitCandidateDAO()


async def _catalog_stats(db: AsyncSession, cutoff: datetime) -> CatalogStats:
    anime_count = (await db.execute(select(func.count(Anime.id)))).scalar_one()
    media_count = (await db.execute(select(func.count(Media.id)))).scalar_one()
    anime_added_7d = (
        await db.execute(
            select(func.count(Anime.id)).where(Anime.created_at >= cutoff)
        )
    ).scalar_one()
    media_added_7d = (
        await db.execute(
            select(func.count(Media.id)).where(Media.created_at >= cutoff)
        )
    ).scalar_one()
    return CatalogStats(
        anime_count=anime_count,
        media_count=media_count,
        anime_added_7d=anime_added_7d,
        media_added_7d=media_added_7d,
    )


async def _jobs_stats(db: AsyncSession, cutoff: datetime) -> JobsStats:
    """One GROUP BY query per kind / status / retryable triple — server
    folds rows into the per-kind shape the schema expects.

    Excludes system-attributed `user_scrape` rows (the children seasonal_sweep
    enqueues with requested_by_user_id=NULL). The Job Health card is meant
    to signal "are users' submissions doing OK?" — counting children would
    drag the success rate down with shows MAL filters as Music/PV. Their
    health is visible per-row in the Jobs Log expander."""
    retryable = func.coalesce(Job.result_summary["retryable"].as_boolean(), True)
    stmt = (
        select(Job.kind, Job.status, retryable.label("retryable"), func.count(Job.id))
        .where(Job.created_at >= cutoff)
        .where(or_(
            Job.kind != JobKind.user_scrape,
            Job.requested_by_user_id.is_not(None),
        ))
        .group_by(Job.kind, Job.status, retryable)
    )
    rows = (await db.execute(stmt)).all()
    by_kind: dict[JobKind, dict[str, int]] = {
        k: {"succeeded": 0, "failed": 0, "retryable_failed": 0}
        for k in JobKind
    }
    for kind, status, is_retryable, count in rows:
        bucket = by_kind[kind]
        if status == JobStatus.succeeded:
            bucket["succeeded"] += count
        elif status == JobStatus.failed:
            bucket["failed"] += count
            if is_retryable:
                bucket["retryable_failed"] += count
    return JobsStats(
        by_kind=[
            JobKindStats(kind=kind.value, **counts)
            for kind, counts in by_kind.items()
        ]
    )


async def _activity_stats(db: AsyncSession, cutoff: datetime) -> ActivityStats:
    new_ratings = (
        await db.execute(
            select(func.count(Ratings.id)).where(Ratings.created_at >= cutoff)
        )
    ).scalar_one()
    scrapes_submitted = (
        await db.execute(
            select(func.count(Job.id))
            .where(Job.kind == JobKind.user_scrape)
            .where(Job.created_at >= cutoff)
            .where(Job.requested_by_user_id.is_not(None))
        )
    ).scalar_one()
    # Active users = distinct user_ids touching ratings OR user-attributed
    # jobs in the window. UNION (not UNION ALL) deduplicates across the
    # two selects, so users who rated AND scraped count once.
    rating_users = select(Ratings.user_id).where(Ratings.created_at >= cutoff)
    job_users = (
        select(Job.requested_by_user_id)
        .where(Job.created_at >= cutoff)
        .where(Job.requested_by_user_id.is_not(None))
    )
    active_users = (
        await db.execute(
            select(func.count()).select_from(rating_users.union(job_users).subquery())
        )
    ).scalar_one()
    return ActivityStats(
        active_users=active_users,
        new_ratings=new_ratings,
        scrapes_submitted=scrapes_submitted,
    )


async def get_overview_stats(db: AsyncSession) -> AdminOverviewStats:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    return AdminOverviewStats(
        catalog=await _catalog_stats(db, cutoff),
        jobs_7d=await _jobs_stats(db, cutoff),
        activity_7d=await _activity_stats(db, cutoff),
    )


async def get_curation_pending_counts(db: AsyncSession) -> CurationPendingCounts:
    """Sequential awaits, not asyncio.gather: AsyncSession can't multiplex
    concurrent ops on one session (see CLAUDE.md LANDMINE). Both queries
    are sub-millisecond pending-only COUNTs, so the cost is irrelevant."""
    return CurationPendingCounts(
        merge=await merge_candidate_dao.count_pending(db),
        split=await split_candidate_dao.count_pending(db),
    )
