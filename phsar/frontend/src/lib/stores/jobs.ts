import { writable, type Readable } from 'svelte/store';

/**
 * /library/add bumps this so the bell refetches /jobs/mine immediately
 * after enqueue, instead of waiting for its 4s/30s poll cadence.
 */
export const jobsRefresh = writable(0);

export function bumpJobsRefresh(): void {
	jobsRefresh.update((n) => n + 1);
}

/**
 * The bell bumps this whenever it observes a new succeeded user_scrape job —
 * /library/add's "Recent additions" panel subscribes and refetches so the
 * UI reflects the new anime without a manual page reload.
 */
export const librarySaved = writable(0);

export function bumpLibrarySaved(): void {
	librarySaved.update((n) => n + 1);
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
