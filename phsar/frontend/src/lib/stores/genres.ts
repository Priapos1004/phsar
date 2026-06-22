import { writable } from 'svelte/store';
import { api } from '$lib/api';
import type { GenreOut } from '$lib/types/api';

// Lowercased genre name → description. Genre descriptions are a global, static
// set (~90 rows), so we fetch them once per session and cache the lookup map
// rather than threading descriptions through every detail/search response.
export const genreDescriptions = writable<Map<string, string>>(new Map());

let loadPromise: Promise<void> | null = null;

/** Fetch genre descriptions once and populate the store. Safe to call from
 * every GenreBadges mount — concurrent callers share one in-flight request. */
export function ensureGenresLoaded(): Promise<void> {
	if (loadPromise) return loadPromise;
	loadPromise = (async () => {
		try {
			const genres = await api.get<GenreOut[]>('/filters/genres');
			const map = new Map<string, string>();
			for (const g of genres) {
				if (g.description) map.set(g.name.toLowerCase(), g.description);
			}
			genreDescriptions.set(map);
		} catch {
			// Tooltips are a progressive enhancement — a failed fetch just means
			// badges render without descriptions. Clear the promise so a later
			// mount retries instead of caching the failure.
			loadPromise = null;
		}
	})();
	return loadPromise;
}
