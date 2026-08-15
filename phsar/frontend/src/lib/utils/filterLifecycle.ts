import { DETAIL_TYPES } from '$lib/utils/navigation';
import { clearRatingsFilter } from '$lib/stores/ratingsFilter';
import { clearWatchlistFilter } from '$lib/stores/watchlistFilter';
import { clearJobsFilter } from '$lib/stores/adminJobsFilter';

/**
 * When a section's list filter is reset.
 *
 * The rule: **clear section S when navigating to a page that is neither inside
 * S nor a detail page.** A detail page is a detour, not a destination — the
 * user opened a row to look at it and is coming back.
 *
 * This has to be driven from the root layout rather than each section's own
 * `+layout.svelte`. `/anime` and `/media` are top-level routes, siblings of
 * `/ratings` and `/watchlist`, so clicking a card unmounts the section layout —
 * an `onDestroy` there fires on exactly the navigation that must NOT reset, and
 * by the time the user leaves the detail page for somewhere else, it is long
 * gone and can no longer fire at all.
 *
 * SvelteKit's `snapshot` export is the other candidate and doesn't fit: it is
 * per route component and keyed to a history entry, so it can't express the
 * admin filter that has to span `/admin` ↔ `/admin/jobs/[uuid]` (two route
 * components, two independent snapshots, no sharing), and its storage keys are
 * SvelteKit-owned, leaving no hook for the per-user wipe on logout.
 */

/** Detour routes, derived from the detail grains so the pair is stated once. */
const DETAIL_ROUTES = DETAIL_TYPES.map((type) => `/${type}`);

interface SectionFilter {
	prefix: string;
	clear: () => void;
}

export const SECTION_FILTERS: readonly SectionFilter[] = [
	{ prefix: '/ratings', clear: clearRatingsFilter },
	{ prefix: '/watchlist', clear: clearWatchlistFilter },
	{ prefix: '/admin', clear: clearJobsFilter },
];

/** Exact match or a `/`-delimited child, so `/ratings` never matches `/ratings-archive`. */
function isWithin(pathname: string, prefix: string): boolean {
	return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function isDetailRoute(pathname: string): boolean {
	return DETAIL_ROUTES.some((route) => isWithin(pathname, route));
}

/** The sections a navigation to `to` should reset. */
export function sectionsToClearFor(to: string): readonly SectionFilter[] {
	if (isDetailRoute(to)) return [];
	return SECTION_FILTERS.filter((section) => !isWithin(to, section.prefix));
}

export function applyFilterLifecycle(to: string): void {
	for (const section of sectionsToClearFor(to)) section.clear();
}
