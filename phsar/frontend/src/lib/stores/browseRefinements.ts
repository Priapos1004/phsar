import type { BrowseCarousel, BrowseFilterSet } from '$lib/types/api';
import { SORT_OPTIONS, type MediaSearchFilters, type SortDir, type SortKey } from '$lib/utils/search';
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

/** `refinement` with `chosen` the one active set of `group`, or none of them. */
export function selectInGroup(group: BrowseFilterSet[], refinement: Refinement, chosen: string | null): Refinement {
	const inGroup = new Set(group.map((s) => s.key));
	const on = refinement.on.filter((k) => !inGroup.has(k));
	const off = refinement.off.filter((k) => !inGroup.has(k));
	for (const set of group) {
		if (set.key === chosen && !set.default_on) on.push(set.key);
		if (set.key !== chosen && set.default_on) off.push(set.key);
	}
	return { ...refinement, on, off };
}

/** The search a see-all runs: the resolved carousel, re-sorted where it is sortable. A
 *  stored sort counts only while it is, so unflagging a carousel overrides any viewer's
 *  choice. */
export function refinedSearch(carousel: BrowseCarousel, refinement: Refinement): MediaSearchFilters {
	const base: MediaSearchFilters = { query: '', search_type: 'title', ...carousel.params };
	return carousel.sortable && refinement.sort
		? { ...base, sort: refinement.sort, sort_dir: refinement.sort_dir }
		: base;
}
