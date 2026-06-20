import { writable } from 'svelte/store';
import { JOB_KIND_LABELS } from '$lib/utils/formatString';
import { STATUS_BADGE } from '$lib/utils/jobBadges';
import type { JobKind, JobStatus } from '$lib/types/api';

interface JobsFilter {
	kind: '' | JobKind;
	status: '' | JobStatus;
}

// Whitelist of valid filter values — anything else (a stale value, an
// injected status) collapses to '' (no filter). Defensive: the store is the
// only source the table fetches from, so the guard keeps a bad value out.
const KIND_VALUES = new Set(Object.keys(JOB_KIND_LABELS));
const STATUS_VALUES = new Set(Object.keys(STATUS_BADGE));

export function sanitizeKind(raw: string | null): '' | JobKind {
	return raw && KIND_VALUES.has(raw) ? (raw as JobKind) : '';
}

export function sanitizeStatus(raw: string | null): '' | JobStatus {
	return raw && STATUS_VALUES.has(raw) ? (raw as JobStatus) : '';
}

// In-SPA memory for the Jobs Log filter. Lives in a module store (not the
// URL) so it survives admin tab switches AND the round-trip through a job
// detail page — both navigate to a bare `/admin?tab=jobs`, and a mounted
// store carries the filter through without re-threading it. Cleared when the
// admin section unmounts (see routes/admin/+layout.svelte) so re-entering
// /admin from elsewhere starts clean.
export const jobsFilter = writable<JobsFilter>({ kind: '', status: '' });

export function clearJobsFilter(): void {
	jobsFilter.set({ kind: '', status: '' });
}
