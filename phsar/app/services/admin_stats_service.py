"""Aggregate stats for the admin Overview tab.

Pure SQL counts against the live catalog. No caching — admin-only,
hit rate is low, the queries are cheap. Revisit if any single query
crosses ~10ms in EXPLAIN against a year-old catalog.

Privacy posture: aggregates only. No per-user breakdowns — the Jobs
Log tab surfaces requested_by_user_id where it's needed for debugging,
but the Overview tab stays leaderboard-free.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.anime_dao import AnimeDAO
from app.daos.merge_candidate_dao import MergeCandidateDAO
from app.daos.split_candidate_dao import SplitCandidateDAO
from app.daos.tag_dao import TagDAO
from app.daos.user_dao import UserDAO
from app.daos.watchlist_dao import WatchlistDAO
from app.models.anime import Anime
from app.models.job import Job, JobKind, JobStatus
from app.models.media import Media
from app.models.ratings import Ratings
from app.models.watchlist import Watchlist
from app.schemas.admin_schema import (
    ActivityStats,
    AdminOverviewStats,
    CatalogStats,
    CurationPendingCounts,
    JobKindStats,
    JobsStats,
    SweepTierBreakdown,
    WatchlistStats,
)

anime_dao = AnimeDAO()
merge_candidate_dao = MergeCandidateDAO()
split_candidate_dao = SplitCandidateDAO()
watchlist_dao = WatchlistDAO()
tag_dao = TagDAO()
user_dao = UserDAO()


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


# A success rate is only a rate if its window holds several runs, so each
# kind's window is sized to how often it runs: a single shared cutoff either
# starves the rare kinds (a weekly sweep in 7 days reads 0% or 100%) or
# dilutes the frequent ones (three bad nights in 90 still reads 97%).
#
# 90d is chosen for `upcoming_sweep` in particular because its runs cluster
# in the last month of each quarter, and those months sit three months
# apart — so a 90-day window always covers one such block wherever you stand
# in the quarter, and never lands in a gap.
#
# Keyed on JobKind with no default, so a new kind fails loudly here rather
# than silently inheriting someone else's cadence.
JOB_HEALTH_WINDOW_DAYS: dict[JobKind, int] = {
    JobKind.user_scrape: 7,
    JobKind.update_sweep: 7,
    JobKind.backup: 7,
    JobKind.seasonal_sweep: 90,
    JobKind.upcoming_sweep: 90,
    JobKind.restore: 90,
}


async def _jobs_stats(db: AsyncSession, now: datetime) -> JobsStats:
    """One GROUP BY query per kind / status / retryable triple — server
    folds rows into the per-kind shape the schema expects.

    Each kind is bounded by its own `JOB_HEALTH_WINDOW_DAYS` entry, as an OR
    of per-kind (kind, cutoff) pairs so the filter reads 1:1 against that
    table.

    Excludes system-attributed `user_scrape` rows (the children seasonal_sweep
    enqueues with requested_by_user_id=NULL). The Job Health card is meant
    to signal "are users' submissions doing OK?" — counting children would
    drag the success rate down with shows MAL filters as Music/PV. Their
    health is visible per-row in the Jobs Log expander."""
    retryable = func.coalesce(Job.result_summary["retryable"].as_boolean(), True)
    user_attributed = Job.requested_by_user_id.is_not(None)
    stmt = (
        select(
            Job.kind, Job.status,
            retryable.label("retryable"),
            user_attributed.label("user_attributed"),
            func.count(Job.id),
        )
        .where(or_(*[
            and_(Job.kind == kind, Job.created_at >= now - timedelta(days=days))
            for kind, days in JOB_HEALTH_WINDOW_DAYS.items()
        ]))
        .where(or_(
            Job.kind != JobKind.user_scrape,
            Job.requested_by_user_id.is_not(None),
        ))
        .group_by(Job.kind, Job.status, retryable, user_attributed)
    )
    rows = (await db.execute(stmt)).all()
    by_kind: dict[JobKind, dict[str, int]] = {
        k: {"succeeded": 0, "failed": 0, "retryable_failed": 0}
        for k in JobKind
    }
    for kind, status, is_retryable, is_user_attributed, count in rows:
        bucket = by_kind[kind]
        if status == JobStatus.succeeded:
            bucket["succeeded"] += count
        elif status == JobStatus.failed:
            bucket["failed"] += count
            # `retryable_failed` only counts USER jobs — the bell's retry
            # button only fires on rows the user owns. System jobs
            # (sweeps, cron backups) retry on their own schedule; counting
            # them here would suggest there's something the admin can
            # poke to recover, when there isn't.
            if is_retryable and is_user_attributed:
                bucket["retryable_failed"] += count
    return JobsStats(
        by_kind=[
            JobKindStats(
                kind=kind.value,
                window_days=JOB_HEALTH_WINDOW_DAYS[kind],
                **counts,
            )
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
    watchlist_modifications = await watchlist_dao.count_modified_since(db, cutoff)
    # Active users = distinct user_ids touching ratings OR user-attributed jobs
    # OR the watchlist in the window. UNION (not UNION ALL) deduplicates across
    # the selects, so a user who rated AND scraped AND watchlisted counts once.
    rating_users = select(Ratings.user_id).where(Ratings.created_at >= cutoff)
    job_users = (
        select(Job.requested_by_user_id)
        .where(Job.created_at >= cutoff)
        .where(Job.requested_by_user_id.is_not(None))
    )
    watchlist_users = select(Watchlist.user_id).where(Watchlist.modified_at >= cutoff)
    active_users = (
        await db.execute(
            select(func.count()).select_from(
                rating_users.union(job_users, watchlist_users).subquery()
            )
        )
    ).scalar_one()
    return ActivityStats(
        active_users=active_users,
        new_ratings=new_ratings,
        scrapes_submitted=scrapes_submitted,
        watchlist_modifications=watchlist_modifications,
    )


async def _sweep_tier_breakdown(db: AsyncSession) -> SweepTierBreakdown:
    counts = await anime_dao.count_by_sweep_tier_priority(db)
    return SweepTierBreakdown(**counts)


async def _media_sweep_tier_breakdown(db: AsyncSession) -> SweepTierBreakdown:
    counts = await anime_dao.count_media_by_sweep_tier_priority(db)
    return SweepTierBreakdown(**counts)


async def _watchlist_stats(db: AsyncSession) -> WatchlistStats:
    total_entries = await watchlist_dao.count_total(db)
    total_anime = await watchlist_dao.count_distinct_anime(db)
    users_with_entries = await watchlist_dao.count_distinct_users(db)
    total_custom_lists = await tag_dao.count_custom_total(db)
    eligible_users = await user_dao.count_non_restricted(db)
    # Two denominators on purpose (see WatchlistStats docstring): entries average over
    # active watchlist users; the custom-list average is ADOPTION, over the whole eligible
    # base (so users who made no list count against it). The `if <denom>` guards protect
    # against div-by-zero, so each division runs only when its denominator is non-zero.
    return WatchlistStats(
        total_entries=total_entries,
        total_anime=total_anime,
        users_with_entries=users_with_entries,
        avg_entries_per_user=round(total_entries / users_with_entries, 1) if users_with_entries else 0.0,
        total_custom_lists=total_custom_lists,
        avg_custom_lists_per_user=round(total_custom_lists / eligible_users, 1) if eligible_users else 0.0,
    )


async def get_overview_stats(db: AsyncSession) -> AdminOverviewStats:
    # One clock read for the whole response, so every number on the card is
    # as of the same instant. Catalog and activity share a 7d cutoff; job
    # health derives a cutoff per kind (see JOB_HEALTH_WINDOW_DAYS).
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    # Sequential awaits — AsyncSession can't multiplex.
    return AdminOverviewStats(
        catalog=await _catalog_stats(db, cutoff),
        jobs=await _jobs_stats(db, now),
        activity_7d=await _activity_stats(db, cutoff),
        watchlist=await _watchlist_stats(db),
        sweep_tiers=await _sweep_tier_breakdown(db),
        media_sweep_tiers=await _media_sweep_tier_breakdown(db),
    )


async def get_curation_pending_counts(db: AsyncSession) -> CurationPendingCounts:
    """Sequential awaits, not asyncio.gather: AsyncSession can't multiplex
    concurrent ops on one session (see .claude/rules/backend.md). Both queries
    are sub-millisecond pending-only COUNTs, so the cost is irrelevant."""
    return CurationPendingCounts(
        merge=await merge_candidate_dao.count_pending(db),
        split=await split_candidate_dao.count_pending(db),
    )
