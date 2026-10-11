import { api } from '$lib/api';
import type { AnimeSearchResult, BrowseCarousel } from '$lib/types/api';
import { fetchAnimeSearchResults, stripForGuest, type MediaSearchFilters } from '$lib/utils/search';

/**
 * Session cache for Browse's requests: a page's carousel list, a see-all's carousel, and
 * the results of rows and see-alls.
 *
 * Opening a tile and coming back would otherwise refetch every row the user had
 * scrolled past, skeletons and all. It follows the section rule instead
 * (`utils/filterLifecycle`): a detail page is a detour and keeps it, leaving Browse
 * drops it, so a later visit sees today's rows.
 *
 * A row over the caller's own ratings or watchlist goes stale on a write to either,
 * so the post-write hooks — `invalidateRatingScores` and `refreshWatchlist` — drop
 * those rows. The rest stay: a write can't change them, and
 * their coverage band and bookmark already follow the write through their own stores.
 * PER-USER, so `clearPerUserStores` clears it.
 */
// One entry per slot, holding the request it was last asked: a see-all keeps a slot per
// carousel, so switching its toggles replaces its list rather than piling one up per
// combination until Browse is left.
const cache = new Map<string, { id: string; pending: Promise<unknown>; personal: boolean }>();

// Concurrent callers share one request. A failure drops its own entry — only while
// it is still the cached one, as in `ratingScores` — so a retry re-requests.
function cached<T>(slot: string, id: string, load: () => Promise<T>, personal = false): Promise<T> {
	const hit = cache.get(slot);
	if (hit?.id === id) return hit.pending as Promise<T>;
	const pending = load();
	cache.set(slot, { id, pending, personal });
	pending.catch(() => {
		if (cache.get(slot)?.pending === pending) cache.delete(slot);
	});
	return pending;
}

export function browsePage(page: string): Promise<BrowseCarousel[]> {
	const key = `page:${page}`;
	return cached(key, key, () => api.get<BrowseCarousel[]>(`/browse/${page}`));
}

/** One carousel resolved with its filter sets switched — a see-all's search. */
export function browseCarousel(key: string, on: string[], off: string[]): Promise<BrowseCarousel> {
	const params = new URLSearchParams();
	for (const k of on) params.append('on', k);
	for (const k of off) params.append('off', k);
	return cached(`carousel:${key}`, `${params}`, () =>
		api.get<BrowseCarousel>(`/browse/carousels/${encodeURIComponent(key)}`, { params }),
	);
}

/** A row's results, keyed by the search itself, which already names everything that
 *  changes them — under `slot` when given, which keeps only the latest search. "Personal"
 *  is the test a guest's shared link is stripped by. */
export function browseRow(params: MediaSearchFilters, limit: number, slot?: string): Promise<AnimeSearchResult[]> {
	const id = JSON.stringify([params, limit]);
	return cached(
		slot ? `see-all:${slot}` : `row:${id}`,
		id,
		() => fetchAnimeSearchResults(params, limit),
		stripForGuest(params).stripped,
	);
}

/** After a rating or watchlist write: drop the rows that read them. */
export function dropPersonalRows(): void {
	for (const [key, entry] of cache) if (entry.personal) cache.delete(key);
}

export function clearBrowseRows(): void {
	cache.clear();
}
