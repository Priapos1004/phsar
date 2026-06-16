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

The dict is hardcoded by design — no per-environment override, no
runtime registration. A KeyError on lookup is the loud signal that a
new JobKind landed without a version assigned.
"""

from typing import Any

from app.models.job import Job, JobKind

JOB_KIND_VERSIONS: dict[JobKind, int] = {
    JobKind.user_scrape: 1,
    # v2 bumps result_summary to a `{counters, media_changes,
    # anime_umbrella_changes}` shape — flat aggregate counters and the
    # bell-shaped genre/studio drift aggregates were dropped.
    # v3 relaxes the genre/studio apply policy (additions + removals
    # now auto-apply; unknown genre tags are still skipped but
    # surfaced via top-level `unknown_genre_tags`). M2M drift `kind`
    # values changed from {additions_applied, additions_unknown,
    # removal_or_replacement, any_change} to {applied,
    # applied_with_unknowns}.
    JobKind.update_sweep: 3,
    JobKind.seasonal_sweep: 1,
    JobKind.backup: 1,
    JobKind.restore: 1,
}


def make_job(kind: JobKind, **kwargs: Any) -> Job:
    """Build a Job row with the current registry version stamped.

    Every Job constructor in the app goes through here so "what version
    did kind X write today?" is answerable from one file. Direct
    `Job(...)` construction still works (the column has a server_default
    of 1 for defence-in-depth), but new call sites should always use
    this helper.
    """
    return Job(kind=kind, version=JOB_KIND_VERSIONS[kind], **kwargs)
