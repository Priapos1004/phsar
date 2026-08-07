import { api } from '$lib/api';
import type { RatingScoreItem } from '$lib/types/api';

/**
 * Session cache for `GET /ratings/scores` — the user's whole rating set.
 *
 * Three independent consumers read it: the `/ratings` page (list + stats), the
 * `/watchlist` Statistics subtab, and `RatingNeighbors` (mounted in RatingCard
 * and BulkRateDialog). It is the heaviest response in the app, so each of them
 * fetching its own copy is the single biggest avoidable cost on those pages —
 * `/ratings` -> `/watchlist?tab=stats` alone would pay for it twice.
 *
 * Coalescing alone would not fix that: those visits are sequential, not
 * concurrent, so this has to be a real cache — which means it can go stale, and
 * the write paths are responsible for saying so via `invalidateRatingScores`.
 * That is the same explicit post-mutation-refresh convention `refreshWatchlist`,
 * `refreshTags` and `refreshSpoilerVisibility` already follow.
 *
 * PER-USER data, so `clearRatingScores` is wired into the layout's
 * `clearPerUserStores` — on logout AND on an A->B user switch (which happens
 * without a null-token transition, since the login page sets the new token
 * directly). Contrast `filterOptions.ts`, which is catalogue-global and stays.
 */
let loadPromise: Promise<RatingScoreItem[]> | null = null;

/**
 * The user's rating set, fetched at most once per session (or per
 * invalidation). Concurrent callers share one in-flight request; a failure
 * clears the promise so a retry re-requests rather than replaying the error.
 */
export function ensureRatingScores(): Promise<RatingScoreItem[]> {
	if (loadPromise) return loadPromise;

	loadPromise = (async () => {
		try {
			return await api.get<RatingScoreItem[]>('/ratings/scores');
		} catch (err) {
			loadPromise = null;
			throw err;
		}
	})();
	return loadPromise;
}

/**
 * Drop the cache after a rating write, so the next reader refetches.
 *
 * Must be called by EVERY path that creates, edits, deletes or rewatches a
 * rating — a missed site shows the user stale scores until they reload, which is
 * the failure mode a per-mount fetch didn't have.
 */
export function invalidateRatingScores(): void {
	loadPromise = null;
}

/** Clear on logout / user switch — see the note above on per-user data.
 *
 *  Deliberately an alias, not a copy: dropping the cache is one operation, and
 *  the two names exist only so a reader can grep for the reason it happened. */
export const clearRatingScores = invalidateRatingScores;
