import { writable } from 'svelte/store';
import { api } from '$lib/api';
import type { Tag } from '$lib/types/api';

// The current user's watchlist tags (default tag first). Cached so the dialogs
// can preselect the default and the overview page's filter/Tags tab share one
// source; refreshed on login + after any tag mutation.
export const tags = writable<Tag[]>([]);

/** Re-fetch the user's tags. Call after login + any tag create/update/delete. */
export async function refreshTags(): Promise<void> {
	try {
		tags.set(await api.get<Tag[]>('/watchlist/tags'));
	} catch {
		// Not authenticated / restricted user / transient error — keep current state.
	}
}

/** Clear on logout / user switch. */
export function clearTags(): void {
	tags.set([]);
}
