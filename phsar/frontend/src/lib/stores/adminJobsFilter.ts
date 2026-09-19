import { JOB_KIND_LABELS } from '$lib/utils/formatString';
import { STATUS_BADGE } from '$lib/utils/jobBadges';
import type { JobKind, JobStatus } from '$lib/types/api';
import { createPersistedFilter } from './persistedFilter';

interface JobsFilter {
	kind: '' | JobKind;
	status: '' | JobStatus;
	/** Which page is shown, 1-based. A list control like the filters beside it: a job
	 *  detour has to come back to the page the row was on, and putting it here
	 *  means `filterLifecycle` already governs when it resets.
	 *
	 *  A page number rather than a row offset, so the stored value stays
	 *  self-describing: an offset would silently mean a different page if the
	 *  table's page size ever changed, with no field shape changing to force a
	 *  version bump. It also keeps the page size in the table that renders it. */
	page: number;
}

// Whitelist of valid filter values — anything else (a stale value, an
// injected status) collapses to '' (no filter). Defensive: the store is the
// only source the table fetches from, so the guard keeps a bad value out.
const KIND_VALUES = new Set(Object.keys(JOB_KIND_LABELS));
const STATUS_VALUES = new Set(Object.keys(STATUS_BADGE));

export function sanitizeKind(raw: unknown): '' | JobKind {
	return typeof raw === 'string' && KIND_VALUES.has(raw) ? (raw as JobKind) : '';
}

export function sanitizeStatus(raw: unknown): '' | JobStatus {
	return typeof raw === 'string' && STATUS_VALUES.has(raw) ? (raw as JobStatus) : '';
}

export function sanitizePage(raw: unknown): number {
	return typeof raw === 'number' && Number.isInteger(raw) && raw >= 1 ? raw : 1;
}

const DEFAULT_JOBS_FILTER: JobsFilter = { kind: '', status: '', page: 1 };

// In-SPA memory for the Jobs Log filter, mirrored to sessionStorage so a
// refresh keeps it. Not the URL: an internal tool doesn't need shareable
// links, and a URL copy would resurrect the filter on browser-back after
// leaving. The same setters the Select writes through already sanitize, so
// rehydration reuses them.
export const jobsFilter = createPersistedFilter<JobsFilter>({
	key: 'phsar.filter.adminJobs',
	version: 2,
	defaults: DEFAULT_JOBS_FILTER,
	sanitize: (raw) => ({
		kind: sanitizeKind(raw.kind),
		status: sanitizeStatus(raw.status),
		page: sanitizePage(raw.page),
	}),
});

/** Reset the Jobs Log filter; fired by `utils/filterLifecycle`. */
export function clearJobsFilter(): void {
	jobsFilter.set({ ...DEFAULT_JOBS_FILTER });
}
