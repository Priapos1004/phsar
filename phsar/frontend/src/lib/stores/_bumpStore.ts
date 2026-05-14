import { writable, type Readable, type Writable } from 'svelte/store';

/**
 * One bump store + a `bump()` setter that increments it. svelte/store's
 * writables always notify subscribers on `update()`, so the bump pattern
 * is just `n => n+1` — every call fires every subscriber exactly once.
 *
 * Use this for cross-component "something happened, refetch now" signals
 * where the value itself is meaningless and only the change event matters.
 */
export function createBumpStore(): readonly [Writable<number>, () => void] {
	const store = writable(0);
	return [store, () => store.update((n) => n + 1)] as const;
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
