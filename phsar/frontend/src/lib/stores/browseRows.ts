import { api } from '$lib/api';
import type { AnimeSearchResult, BrowseCarousel } from '$lib/types/api';
import { fetchAnimeSearchResults, stripForGuest, type MediaSearchFilters } from '$lib/utils/search';

/**
 * Session cache for Browse: a page's carousel list and each row's results.
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
const cache = new Map<string, { pending: Promise<unknown>; personal: boolean }>();

// Concurrent callers share one request. A failure drops its own entry — only while
// it is still the cached one, as in `ratingScores` — so a retry re-requests.
function cached<T>(key: string, load: () => Promise<T>, personal = false): Promise<T> {
	const hit = cache.get(key);
	if (hit) return hit.pending as Promise<T>;
	const pending = load();
	cache.set(key, { pending, personal });
	pending.catch(() => {
		if (cache.get(key)?.pending === pending) cache.delete(key);
	});
	return pending;
}

export function browsePage(page: string): Promise<BrowseCarousel[]> {
	return cached(`page:${page}`, () => api.get<BrowseCarousel[]>(`/browse/${page}`));
}

/** A row's results. Keyed by the search itself, which already names everything that
 *  changes them. "Personal" is the test a guest's shared link is stripped by. */
export function browseRow(params: MediaSearchFilters, limit: number): Promise<AnimeSearchResult[]> {
	return cached(
		`row:${JSON.stringify([params, limit])}`,
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
