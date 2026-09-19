"""Per-JobKind schema version registry.

The `jobs.version` column lets us evolve a kind's `result_summary` shape
without breaking the admin Jobs Log against historical rows. Frontend
switches on `(kind, version)` to pick a parser; bumping the integer
here is the only producer-side change required when a payload shape
changes.

Bump rules:
- Net-new key with safe default: no bump (frontend treats missing as
  default).
- Removed key, renamed key, reshaped nested structure: bump.
- A net-new key only the job-detail page reads also belongs in
  `LIST_OMITTED_SUMMARY_KEYS` below, or it silently re-inflates the
  Jobs Log list response.

The dict is hardcoded by design — no per-environment override, no
runtime registration. A KeyError on lookup is the loud signal that a
new JobKind landed without a version assigned.
"""

from typing import Any

from app.models.job import Job, JobKind

JOB_KIND_VERSIONS: dict[JobKind, int] = {
    JobKind.user_scrape: 1,
    # Entry shapes are typed in the frontend's `types/api.ts`.
    #   v2  `{counters, media_changes, anime_umbrella_changes}`; flat aggregates gone
    #   v3  top-level `unknown_genre_tags`; drift `kind` is {applied, applied_with_unknowns}
    #   v4  `counters.step1_failed` + `step1_failures[]`
    #   v5  counters go media-grained (`media_refreshed`, `anime_touched`,
    #       `media_skipped_fresh`); the `anime_with_*` pair is gone; `probe_failures[]`
    #   v6  `counters.probe_attached_media_count` + `probe_attached_anime[]`
    #   v7  `counters.hentai_removed_count` + `hentai_removed[]`
    #   v8  `counters.delete_candidates_raised`
    #   v9  a MAL 404 stops failing its anime: `gone_upstream[]` replaces the
    #       `step1_failures[].gone_media_*` keys, so siblings refresh normally
    #
    # A version whose only change is net-new keys bumps anyway, against the
    # rules above, and that is the one thing worth knowing about this list: a
    # reader must be able to tell a genuine zero or empty list from a row too
    # old to have counted at all.
    JobKind.update_sweep: 9,
    # Both season sweeps come off ONE dispatcher and so write one shape:
    # {season_entries, new_entries_enqueued, dedup_skipped, season_year, season_name}.
    # The season pair is additive with a safe default and the frontend gates on its
    # presence (an older row just drops the season prefix), so it stays v1.
    JobKind.seasonal_sweep: 1,
    JobKind.upcoming_sweep: 1,
    JobKind.backup: 1,
    JobKind.restore: 1,
}

# result_summary keys the Jobs Log *list* never reads — only the
# /admin/jobs/{uuid} detail page renders them. They dominate an
# update_sweep row (media_changes alone is one 13-key object per changed
# media, up to JOBS_SWEEP_MAX_PER_RUN of them), while the list shows
# nothing but `counters` scalars and `unknown_genre_tags`. A 50-row page
# on a 3s poll ships that repeatedly for nothing, so
# `JobDAO.list_admin_paginated` projects them out.
#
# A denylist rather than an allowlist of the keys the list *does* read:
# an allowlist would have to enumerate every kind's small keys
# (retryable, anime_count, filename, restored_from, ...) and a forgotten
# entry would blank a Jobs Log cell instead of merely bloating a payload.
# The cost is that a future heavy key must be added here deliberately —
# see the bump rules in the module docstring.
#
# Flat rather than keyed by kind, because the query applies it to every
# row (`jsonb - text[]` is a no-op for keys a row doesn't carry). A dict
# would claim a per-kind precision the projection doesn't deliver, and
# the claim would be wrong in the one direction that matters: a name
# that is detail-only for one kind but *rendered* for another would be
# stripped from both. Keep these names unique to their kind, or switch
# the query to a CASE on `jobs.kind` at the same time as adding one.
LIST_OMITTED_SUMMARY_KEYS: tuple[str, ...] = (
    "media_changes",           # update_sweep v2
    "anime_umbrella_changes",  # update_sweep v2
    "step1_failures",          # update_sweep v4
    "probe_failures",          # update_sweep v5
    "probe_attached_anime",    # update_sweep v6
    "hentai_removed",          # update_sweep v7
    "gone_upstream",           # update_sweep v9
)


def make_job(kind: JobKind, **kwargs: Any) -> Job:
    """Build a Job row with the current registry version stamped.

    Every Job constructor in the app goes through here so "what version
    did kind X write today?" is answerable from one file. Direct
    `Job(...)` construction still works (the column has a server_default
    of 1 for defence-in-depth), but new call sites should always use
    this helper.
    """
    return Job(kind=kind, version=JOB_KIND_VERSIONS[kind], **kwargs)
