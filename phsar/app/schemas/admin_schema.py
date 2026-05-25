from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.users import RoleType


class PendingReclassification(BaseModel):
    """One media row whose relation_type would change if the admin
    proceeds with the merge. Surfaced under each pending candidate so
    the admin sees the consequence of the merge — substance-gate
    demotions, alternative-version labels, anchor flips reflected as
    main → side_story — before clicking the button."""
    media_uuid: str
    title: str
    old_relation_type: str
    new_relation_type: str


class MergeCandidateAnimeSummary(BaseModel):
    """Side-by-side card payload for the admin UI: just enough to compare
    two anime at a glance without round-tripping back to /anime/{uuid}.
    `earliest_aired_from` and `rating_count` drive the recommended-keep
    ordering — admin sees them as visible justification for which side is
    surfaced as A."""
    uuid: str
    title: str
    name_eng: str | None = None
    name_jap: str | None = None
    media_count: int
    studios: list[str]
    earliest_year: int | None = None
    earliest_aired_from: datetime | None = None
    rating_count: int = 0


class MergeCandidateListItem(BaseModel):
    uuid: str
    similarity_score: float
    detected_by: str
    created_at: datetime
    anime_a: MergeCandidateAnimeSummary
    anime_b: MergeCandidateAnimeSummary
    pending_reclassifications: list[PendingReclassification] = Field(default_factory=list)


class MergeRequest(BaseModel):
    """Optional body for POST /admin/merge-candidates/{uuid}/merge. When
    `keep_uuid` matches the candidate's anime_b, the merge swaps direction
    so the admin's preferred side is the survivor."""
    keep_uuid: UUID | None = None


class MergeResult(BaseModel):
    """Returned after a successful merge so the frontend can navigate to
    the surviving anime detail page."""
    surviving_anime_uuid: str


class MergeBackfillResult(BaseModel):
    """Returned by the manual re-detect trigger. `inserted` is the number
    of new pending pairs created by this run; the backfiller is idempotent
    so repeated clicks return 0 once everything is flagged."""
    inserted: int


class SplitClusterMember(BaseModel):
    """One media row inside a proposed split cluster. The admin sees a
    list of these per cluster to verify which media will land in the
    new anime row after split execution."""
    media_uuid: str
    mal_id: int
    title: str
    media_type: str
    relation_type: str


class SplitClusterPreview(BaseModel):
    """A single disjoint substance-passing chain detected under the
    source anime. After split execution, one new Anime row gets created
    per cluster, anchored at `suggested_anchor_mal_id`. `bridge_edges`
    surfaces the MAL relations that absorbed this cluster so admin sees
    WHY it was bundled (e.g., a single `spin-off` edge to the parent's
    main, or no edge at all for orphans via dropped/dangling relations).
    """
    suggested_anchor_mal_id: int
    members: list[SplitClusterMember]
    substance_member_mal_ids: list[int]
    bridge_edges: list[tuple[int, int, str]] = Field(default_factory=list)


class SplitCandidateListItem(BaseModel):
    """One row in the admin Split Candidates queue. Mirrors
    MergeCandidateListItem's shape but holds N clusters instead of an
    A/B pair — the splitter is single-source-multi-target."""
    uuid: str
    detected_by: str
    created_at: datetime
    source_anime: MergeCandidateAnimeSummary
    clusters: list[SplitClusterPreview]


class SplitResult(BaseModel):
    """Returned after a successful split. `surviving_anime_uuid` is the
    source anime (its media set is smaller now). `new_anime_uuids` are
    the rows created from the orphan clusters — one per cluster."""
    surviving_anime_uuid: str
    new_anime_uuids: list[str]


class SplitBackfillResult(BaseModel):
    """Returned by the manual re-detect trigger for SplitCandidates.
    `inserted` counts new or updated rows; idempotent on no-change reruns."""
    inserted: int


class ScheduledSweepResponse(BaseModel):
    """Returned by POST /admin/jobs/schedule-sweep so the cron can confirm
    the job is queued and (in dev) the admin can poll /maintenance/status
    against the same timestamp."""
    job_uuid: UUID
    scheduled_at: datetime


class JobEnqueuedResponse(BaseModel):
    """Lightweight 202 payload returned when an endpoint enqueues a job
    instead of doing the work synchronously. The bell + the relevant card
    pick the new row up via /jobs/mine (manual) or the dump list refresh
    (cron) — the uuid lets the caller poll /jobs/{uuid} directly if it
    wants tighter feedback than the bell's interval."""
    job_uuid: UUID


class NightlyScheduleResponse(BaseModel):
    """Returned by POST /admin/jobs/schedule-nightly. The combined cron
    endpoint enqueues a backup (immediate), an update_sweep (delayed so the
    banner can warm up), and — only on Sundays UTC — a seasonal_sweep with
    the same delay. `seasonal_sweep_uuid` is null on weekdays so callers can
    distinguish 'didn't run today' from 'failed to enqueue'."""
    backup_uuid: UUID
    update_sweep_uuid: UUID
    seasonal_sweep_uuid: UUID | None = None
    scheduled_at: datetime


class CatalogStats(BaseModel):
    anime_count: int
    media_count: int
    anime_added_7d: int
    media_added_7d: int


class JobKindStats(BaseModel):
    """Per-kind breakdown of jobs created in the last 7 days. `failed`
    counts both retryable and permanent failures; `retryable_failed` is
    a subset showing how many of those `failed` rows could still recover
    (so admin can spot user_scrape jobs stuck on transient MAL outages
    vs. permanently-dead deterministic failures)."""
    kind: str
    succeeded: int
    failed: int
    retryable_failed: int


class JobsStats(BaseModel):
    by_kind: list[JobKindStats]


class ActivityStats(BaseModel):
    """User activity counters over the last 7 days. `active_users` is
    distinct users with at least one rating change or scrape submission
    in the window — system jobs (requested_by_user_id IS NULL) excluded."""
    active_users: int
    new_ratings: int
    scrapes_submitted: int


class AdminOverviewStats(BaseModel):
    catalog: CatalogStats
    jobs_7d: JobsStats
    activity_7d: ActivityStats


class ExpiryPreset(int, Enum):
    """Allowed token expiry durations in days."""
    one_day = 1
    one_week = 7
    one_month = 30


class RegistrationTokenCreateRequest(BaseModel):
    role: RoleType
    expires_in_days: ExpiryPreset = ExpiryPreset.one_week

    @field_validator("role")
    @classmethod
    def restrict_role(cls, v: RoleType) -> RoleType:
        if v == RoleType.Admin:
            raise ValueError("Cannot create registration tokens with admin role.")
        return v


class RegistrationTokenListItem(BaseModel):
    uuid: str
    token: str
    role: RoleType
    status: Literal["active", "used", "expired"]
    created_by: str
    created_at: datetime
    expires_on: datetime
    used_by: str | None = None
    used_at: datetime | None = None
