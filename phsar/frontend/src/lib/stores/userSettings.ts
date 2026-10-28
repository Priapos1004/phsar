import { derived, writable } from 'svelte/store';
import type { UserSettings } from '$lib/types/api';

export const userSettings = writable<UserSettings | null>(null);

/** The view a search without one runs in. One source, since `navigateToSearch` must name
 * the same default search the pages run. */
export const defaultSearchView = derived(userSettings, ($s): UserSettings['default_search_view'] => $s?.default_search_view ?? 'anime');
