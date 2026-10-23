import type { BrowseCarousel, BrowseFilterSet } from '$lib/types/api';
import { forGuest, SORT_OPTIONS, type MediaSearchFilters, type SortDir, type SortKey } from '$lib/utils/search';
import { createPersistedFilter, DIRECTION_KEYS, pickStrings } from './persistedFilter';

/**
 * A carousel see-all's choices: its filter sets switched against their defaults — the
 * `on` / `off` lists the backend's resolver takes (docs/features/browse.md) — and, on a
 * sortable carousel, a sort replacing its own.
 */
export interface Refinement {
	on: string[];
	off: string[];
	sort?: SortKey;
	sort_dir?: SortDir;
}

export const NO_REFINEMENT: Refinement = { on: [], off: [] };

function sanitizeRefinement(raw: Record<string, unknown>): Refinement {
	const refinement: Refinement = { on: pickStrings(raw.on), off: pickStrings(raw.off) };
	if (SORT_OPTIONS.some((o) => o.value === raw.sort)) refinement.sort = raw.sort as SortKey;
	if (typeof raw.sort_dir === 'string' && Object.hasOwn(DIRECTION_KEYS, raw.sort_dir)) {
		refinement.sort_dir = raw.sort_dir as SortDir;
	}
	return refinement;
}

/** Per carousel key. Kept across a detail detour, reset on leaving Browse
 *  (`utils/filterLifecycle`). */
export const browseRefinements = createPersistedFilter<Record<string, Refinement>>({
	key: 'phsar.filter.browse',
	version: 1,
	defaults: {},
	sanitize: (raw) =>
		Object.fromEntries(
			Object.entries(raw)
				.filter(([, value]) => value && typeof value === 'object' && !Array.isArray(value))
				.map(([key, value]) => [key, sanitizeRefinement(value as Record<string, unknown>)]),
		),
});

export function clearBrowseRefinements(): void {
	browseRefinements.set({});
}

export function isSetActive(set: BrowseFilterSet, refinement: Refinement): boolean {
	return set.default_on ? !refinement.off.includes(set.key) : refinement.on.includes(set.key);
}

/** A group's heading, by the param its sets share; a lone set's label says it all. Every param the seeded sets share needs one
 *  (`test_every_shared_param_has_a_heading`). */
export const GROUP_HEADINGS: Record<string, string> = { top_percent: 'Top', watchlisted: 'Watchlist', rated: 'Watched' };

// The Top step `widened` steps up from, and to.
const NARROW = 'top-50';
const WIDE = 'top-75';

/** The offered sets grouped by a shared param (docs/features/browse.md). Position order;
 *  a set joins the first group sharing a param with it. */
export function filterSetGroups(sets: BrowseFilterSet[]): BrowseFilterSet[][] {
	const groups: BrowseFilterSet[][] = [];
	for (const set of sets) {
		const params = Object.keys(set.params);
		const group = groups.find((g) => g.some((s) => Object.keys(s.params).some((p) => params.includes(p))));
		if (group) group.push(set);
		else groups.push([set]);
	}
	return groups;
}

/** `refinement` with `chosen` the one active set of `group`, or none of them. A chosen set
 *  is recorded even where it is a default: left implicit it would read as no choice
 *  (docs/features/browse.md#a-thin-row-widens). */
export function selectInGroup(group: BrowseFilterSet[], refinement: Refinement, chosen: string | null): Refinement {
	const inGroup = new Set(group.map((s) => s.key));
	const on = refinement.on.filter((k) => !inGroup.has(k));
	const off = refinement.off.filter((k) => !inGroup.has(k));
	for (const set of group) {
		if (set.key === chosen) on.push(set.key);
		if (set.key !== chosen && set.default_on) off.push(set.key);
	}
	return { ...refinement, on, off };
}

/** A carousel with the refinement it lists under. */
export type Step = { carousel: BrowseCarousel; refinement: Refinement };

/** How many anime a browse row shows. */
export const ROW_SIZE = 25;
/** A pool smaller than this at the default Top 50% widens (`widened`). Above a row's
 *  worth, so a row isn't left with its last few tiles before it widens. */
export const WIDEN_BELOW = 35;

/**
 * `carousel` and `refinement` stepped from a default Top 50% up to Top 75%, or null where
 * the rule doesn't apply (docs/features/browse.md#a-thin-row-widens). The params are merged
 * here as the backend's resolver would, so widening costs no second carousel request.
 */
export function widened(carousel: BrowseCarousel, refinement: Refinement): Step | null {
	const narrow = carousel.filter_sets.find((s) => s.key === NARROW && s.default_on);
	const wide = carousel.filter_sets.find((s) => s.key === WIDE);
	const chosen = [...refinement.on, ...refinement.off].some((key) =>
		carousel.filter_sets.some((s) => s.key === key && 'top_percent' in s.params),
	);
	if (!narrow || !wide || chosen) return null;
	return {
		carousel: { ...carousel, params: { ...carousel.params, ...wide.params } },
		refinement: { ...refinement, on: [...refinement.on, wide.key], off: [...refinement.off, narrow.key] },
	};
}

/** The search a carousel runs, for its row and its see-all alike, so those and Open in
 *  search agree for a guest: the resolved carousel, re-sorted where it is sortable. A
 *  stored sort counts only while it is, so unflagging a carousel overrides any viewer's
 *  choice. */
export function refinedSearch(carousel: BrowseCarousel, refinement: Refinement, isGuest: boolean): MediaSearchFilters {
	const base: MediaSearchFilters = { query: '', search_type: 'title', ...carousel.params };
	const search = carousel.sortable && refinement.sort
		? { ...base, sort: refinement.sort, sort_dir: refinement.sort_dir }
		: base;
	return isGuest ? forGuest(search) : search;
}
