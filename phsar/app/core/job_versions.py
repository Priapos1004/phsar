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
    # v2 bumps result_summary to a `{counters, media_changes,
    # anime_umbrella_changes}` shape — flat aggregate counters and the
    # bell-shaped genre/studio drift aggregates were dropped.
    # v3 relaxes the genre/studio apply policy (additions + removals
    # now auto-apply; unknown genre tags are still skipped but
    # surfaced via top-level `unknown_genre_tags`). M2M drift `kind`
    # values changed from {additions_applied, additions_unknown,
    # removal_or_replacement, any_change} to {applied,
    # applied_with_unknowns}.
    # v4 adds `counters.step1_failed` + top-level `step1_failures[]`
    # (anime skipped because step-1 refresh raised). These are net-new
    # keys with safe defaults, so by the bump rules above they wouldn't
    # require a bump — but we bump anyway so the frontend can tell a v4
    # `step1_failed: 0` (genuinely zero) from a v3 row that never tracked
    # it (rendered "—", not a misleading 0).
    # v5 (v0.14.8) converts the sweep from anime-level to media-level
    # refresh. Counters go media-grained: `anime_refreshed` -> media_refreshed,
    # plus new `anime_touched` (distinct anime with >=1 media refreshed) and
    # `media_skipped_fresh` (present-but-not-due media); the
    # anime_with_dynamic/static_changes pair is dropped (an anime is no
    # longer the work unit — media_with_* carries the signal). Also adds
    # top-level `probe_failures[]` (symmetric to step1_failures[]). The
    # rename + removals force the bump (net-new keys alone wouldn't); the
    # frontend keeps v2/v3/v4 parsers so historical rows still render.
    # v6 (v0.14.9) adds `counters.probe_attached_media_count` + top-level
    # `probe_attached_anime[]` (per-anime list of media the relations probe
    # attached: {anime_uuid, title, media: [{media_uuid, title}, ...]}).
    # Net-new keys with safe defaults wouldn't force a bump, but — like the
    # v4 step1_failed bump — we bump so the frontend can tell a genuinely
    # empty v6 list from a pre-v6 row that never tracked it (the "Attached
    # via probe" card + Jobs Log blue tint gate on version >= 6).
    # v7 (v0.14.14) adds `counters.hentai_removed_count` + top-level
    # `hentai_removed[]` (anime deleted mid-sweep because MAL flipped them to
    # Hentai: {anime_uuid, title, name_eng, name_jap, mal_ids}). Net-new keys
    # with safe defaults; bumped (like v4/v6) so the frontend renders a
    # genuinely-empty v7 list distinctly from a pre-v7 row that never tracked it.
    # v8 adds `counters.delete_candidates_raised` (delete candidates the sweep
    # raised — a MAL 404 mid-sweep, plus the end-of-sweep low-signal pass) and
    # `step1_failures[].gone_media_id` / `.gone_media_mal_id`, set only on the
    # 404 entries so the detail page can link a failure to the candidate it
    # raised. Net-new keys with safe defaults; bumped like v4/v6/v7 so the Jobs
    # Log can tell a genuine zero from a pre-v8 row that never counted them —
    # the row tint gates on version >= 8.
    # v9 moves a MAL 404 out of the failure path entirely. It is handled in
    # the per-media refresh loop instead of raising, so it no longer fails its
    # anime (siblings refresh normally) and no longer appears in
    # `step1_failures[]` — the removed `.gone_media_id` / `.gone_media_mal_id`
    # keys are what force this bump rather than the convention v4/v6/v7/v8
    # followed. Replaced by top-level `gone_upstream[]`: one entry per dead
    # media, {anime_uuid, anime_title, anime_name_eng, anime_name_jap,
    # media_uuid, media_title, media_name_eng, media_name_jap, media_mal_id,
    # candidate_raised}. No paired counter — `counters.delete_candidates_raised`
    # (v8) still carries what the Jobs Log tints on, and the detail card reads
    # the list's own length.
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
