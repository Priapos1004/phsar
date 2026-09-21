import { writable } from 'svelte/store';
import { api } from '$lib/api';
import type { AnimeRatingCoverage, CoverageTier } from '$lib/types/api';

/**
 * anime UUID → how completely the caller has rated it. Drives the coverage
 * marking on cards. Anime the user has never rated are ABSENT, not present with
 * a falsy tier, which is what keeps this bounded by their library rather than
 * the catalogue.
 *
 * LAZY, unlike `watchlistTags`, and for a reason that is about where it is read:
 * the bookmark set is read on the same pages watchlist writes happen, so an
 * eager refresh paints something. Coverage is read on exactly two surfaces —
 * `/search` and `/ratings` — and none of the rating-write paths lives on either.
 * Refreshing on write would fetch a library-sized aggregate that nothing mounted
 * reads, once per rating, and racing two of those can leave the older response
 * winning. So the write path only marks it stale, and the two readers `ensure`.
 *
 * Deliberately NOT derived from `ratingScores` — that response carries only rated
 * media, so it has the numerator and never the denominator.
 */
export const ratingCoverage = writable<Map<string, CoverageTier>>(new Map());

// One variable, not a `loaded` flag beside an in-flight handle: the promise's own
// identity is what tells a settling request whether it is still the current one.
// Without that check an invalidate landing mid-flight lets the pre-write response
// win and then marks the store fresh, so the staleness sticks until the next
// write. `ratingScores` guards the same race the same way.
let loadPromise: Promise<void> | null = null;

/**
 * Populate the store unless it is already current. Safe to call on every mount;
 * concurrent callers share the one request.
 *
 * Never rejects — both callers fire it unawaited, where a rejection would be an
 * unhandled one.
 */
export function ensureRatingCoverage(): Promise<void> {
	if (loadPromise) return loadPromise;

	const pending: Promise<void> = api
		.get<AnimeRatingCoverage[]>('/ratings/coverage')
		.then((entries) => {
			// Superseded by an invalidate or a user switch while in flight: drop it,
			// and leave the cache empty so the next reader refetches.
			if (loadPromise !== pending) return;
			ratingCoverage.set(new Map(entries.map((e) => [e.anime_uuid, e.tier])));
		})
		.catch(() => {
			// Not authenticated / restricted user / transient error — clear the cache
			// so a retry re-requests rather than replaying the failure.
			if (loadPromise === pending) loadPromise = null;
		});

	loadPromise = pending;
	return pending;
}

/**
 * Mark stale after a rating write. Called from `invalidateRatingScores`, which
 * every write path already has to call — so there is no second list of sites to
 * keep in step.
 */
export function invalidateRatingCoverage(): void {
	loadPromise = null;
}

/** Clear on logout / user switch — the map itself, so the next user cannot see
 *  the previous one's tiers in the gap before their own fetch lands. */
export function clearRatingCoverage(): void {
	loadPromise = null;
	ratingCoverage.set(new Map());
}
