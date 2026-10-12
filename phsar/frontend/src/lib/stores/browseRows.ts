import { api } from '$lib/api';
import type { AnimeSearchResult, BrowseCarousel, BrowsePageKey } from '$lib/types/api';
import { fetchAnimeSearchResults, readsOwnData, type MediaSearchFilters } from '$lib/utils/search';
import { catalogueChanged, onBump } from './jobs';

/**
 * Session cache for the browse requests: a page's carousel list, a see-all's carousel, and
 * the results of rows and see-alls.
 *
 * Opening a tile and coming back would otherwise refetch every row the user had
 * scrolled past, skeletons and all. Browse's entries follow the section rule
 * (`utils/filterLifecycle`): a detail page is a detour and keeps them, leaving Browse
 * drops them, so a later visit sees today's rows. Home's outlive any navigation, since it
 * is the page users keep returning to and its rows change only with the catalogue. A
 * catalogue change (`catalogueChanged`) drops every entry, and every entry ends with its
 * UTC day, when the daily shuffle moves on.
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
const cache = new Map<string, { id: string; pending: Promise<unknown>; personal: boolean; home: boolean }>();

// Concurrent callers share one request. A failure drops its own entry — only while
// it is still the cached one, as in `ratingScores` — so a retry re-requests.
function cached<T>(
	slot: string, id: string, load: () => Promise<T>, { personal = false, home = false } = {},
): Promise<T> {
	const dayId = `${new Date().toISOString().slice(0, 10)} ${id}`;
	const hit = cache.get(slot);
	if (hit?.id === dayId) return hit.pending as Promise<T>;
	const pending = load();
	cache.set(slot, { id: dayId, pending, personal, home });
	pending.catch(() => {
		if (cache.get(slot)?.pending === pending) cache.delete(slot);
	});
	return pending;
}

export function browsePage(page: BrowsePageKey): Promise<BrowseCarousel[]> {
	const key = `page:${page}`;
	return cached(key, key, () => api.get<BrowseCarousel[]>(`/browse/${page}`), { home: page === 'home' });
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

/** A row's results, keyed by the search itself, which names everything that changes them —
 *  under `slot` when given, which keeps only the latest search. `page` decides only how long
 *  the entry lives: Home's outlive leaving Browse. */
export function browseRow(
	params: MediaSearchFilters, limit: number, { slot, page }: { slot?: string; page?: BrowsePageKey | null } = {},
): Promise<AnimeSearchResult[]> {
	const id = JSON.stringify([params, limit]);
	return cached(
		slot ? `see-all:${slot}` : `row:${id}`,
		id,
		() => fetchAnimeSearchResults(params, limit),
		{ personal: readsOwnData(params), home: page === 'home' },
	);
}

/** After a rating or watchlist write: drop the rows that read them. */
export function dropPersonalRows(): void {
	for (const [key, entry] of cache) if (entry.personal) cache.delete(key);
}

/** Leaving Browse: drop its entries, and keep Home's. */
export function clearSectionRows(): void {
	for (const [key, entry] of cache) if (!entry.home) cache.delete(key);
}

export function clearBrowseRows(): void {
	cache.clear();
}

onBump(catalogueChanged, clearBrowseRows);
