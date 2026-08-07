import { api } from '$lib/api';
import type { FilterOptions } from '$lib/types/api';
import { librarySaved, onBump } from './jobs';

/** The endpoint's two variants. Typed rather than `string` because the key set
 *  is what makes this cache correct — a typo would silently allocate a third
 *  slot and pay for another request. */
type ViewType = 'anime' | 'media';

/**
 * Session cache for `GET /filters/options`, keyed by `view_type`.
 *
 * Worth caching because the endpoint is 8-15 backend round trips (46-66 ms) for
 * slider bounds and dropdown values that change only when the CATALOGUE does,
 * while `SearchBar` — its only caller — mounts on both `/` and `/search`, so
 * every hop between them would otherwise refetch, as would every anime <-> media
 * toggle.
 *
 * Same shape as `genres.ts`: a stored promise, so concurrent callers share one
 * in-flight request and a failure evicts the key rather than caching itself.
 *
 * Deliberately NOT cleared on logout or user switch (contrast `ratingScores.ts`):
 * filter options are catalogue-global, identical for every account, and contain
 * nothing personal.
 */
const cache = new Map<ViewType, Promise<FilterOptions>>();

/** Fetch a view's filter options, reusing the session's copy when present. */
export function ensureFilterOptions(viewType: ViewType): Promise<FilterOptions> {
	const existing = cache.get(viewType);
	if (existing) return existing;

	const pending = (async () => {
		try {
			const params = new URLSearchParams({ view_type: viewType });
			return await api.get<FilterOptions>('/filters/options', { params });
		} catch (err) {
			// Drop the key so a later mount retries instead of replaying the failure
			// for the rest of the session; the caller still sees the rejection.
			cache.delete(viewType);
			throw err;
		}
	})();
	cache.set(viewType, pending);
	return pending;
}

/** Drop the cache — the catalogue changed under it. */
export function clearFilterOptions(): void {
	cache.clear();
}

// A finished scrape adds media, which can widen a slider's bounds or introduce a
// new season/studio/genre. `librarySaved` is bumped by the JobBell when it sees a
// user_scrape succeed, so hooking it here keeps the dominant staleness case right
// without any component having to remember. `onBump` (not a raw subscribe) skips
// svelte's initial synchronous fire.
//
// Module scope rather than a component: the bump can land while no SearchBar is
// mounted, and only the NEXT mount cares.
//
// A catalogue change from another user or the nightly sweep still needs a reload.
// `genres.ts` accepts the same limit; both are session caches of catalogue data,
// not live views of it.
onBump(librarySaved, clearFilterOptions);
