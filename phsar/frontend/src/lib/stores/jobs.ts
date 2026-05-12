import { get, writable, type Readable } from 'svelte/store';
import type { Job } from '$lib/types/api';

/**
 * One bump store + a `bump()` setter that increments it. svelte/store's
 * writables always notify subscribers on `update()`, so the bump pattern
 * is just `n => n+1` — every call fires every subscriber exactly once.
 */
function createBumpStore() {
	const store = writable(0);
	return [store, () => store.update((n) => n + 1)] as const;
}

// /library/add bumps this so the bell refetches /jobs/mine immediately
// after enqueue, instead of waiting for its 30s idle poll.
export const [jobsRefresh, bumpJobsRefresh] = createBumpStore();

// The bell bumps this whenever it observes a newly-succeeded user_scrape job;
// /library/add's "Recent additions" panel subscribes and refetches.
export const [librarySaved, bumpLibrarySaved] = createBumpStore();

// The bell bumps this whenever it observes a newly-succeeded backup job; the
// admin panel's BackupsCard subscribes and refetches the dump list. Cron
// backups stay system jobs and never reach the bell — the card's onMount
// picks those up the next time the admin opens the page.
export const [backupSaved, bumpBackupSaved] = createBumpStore();

/**
 * In-memory list of jobs that callers (e.g. BackupsCard, /library/add) push
 * right after a successful enqueue, so the bell can render the queued row
 * synchronously without waiting for the next /jobs/mine fetch to round-trip.
 *
 * The bell merges these with its fetched list (deduped by UUID, fetched
 * wins) and calls `reconcileOptimisticJobs(fresh)` after every fetch.
 */
export const optimisticJobs = writable<Job[]>([]);

export function addOptimisticJob(job: Job): void {
	// svelte/store writables notify on every set/update regardless of whether
	// the value reference changed, so dedupe outside `update()` to avoid
	// firing every subscriber on a no-op re-add.
	const current = get(optimisticJobs);
	if (current.some((j) => j.uuid === job.uuid)) return;
	optimisticJobs.set([job, ...current]);
}

export function reconcileOptimisticJobs(fetched: Job[]): void {
	// Called after every /jobs/mine poll (every 2s while jobs are active).
	// Short-circuit when the store is empty OR no overlap with fetched so
	// idle polls don't churn the bell's $derived(mergedJobs) every tick.
	const current = get(optimisticJobs);
	if (current.length === 0) return;
	const fetchedUuids = new Set(fetched.map((j) => j.uuid));
	const next = current.filter((j) => !fetchedUuids.has(j.uuid));
	if (next.length === current.length) return;
	optimisticJobs.set(next);
}

/**
 * Subscribe to a store and run `fn` on every change EXCEPT the initial
 * synchronous fire that svelte/store does at subscribe time. Used by
 * components that already do their first fetch on mount and only want the
 * store to drive subsequent refreshes.
 *
 * Returns the unsubscribe function — caller is expected to wire it into
 * onDestroy (or assign to a $effect cleanup).
 */
export function onBump(store: Readable<unknown>, fn: () => void): () => void {
	let initial = true;
	return store.subscribe(() => {
		if (initial) {
			initial = false;
			return;
		}
		fn();
	});
}
