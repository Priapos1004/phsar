import { writable, derived } from 'svelte/store';
import { api } from '$lib/api';
import type { SpoilerVisibility } from '$lib/types/api';

export const spoilerVisibility = writable<SpoilerVisibility | null>(null);

export const visibleMediaSet = derived(spoilerVisibility, ($sv) =>
	$sv ? new Set($sv.visible_media_uuids) : new Set<string>()
);

/** Re-fetch spoiler visibility from the backend (call after rating CRUD). */
export async function refreshSpoilerVisibility(): Promise<void> {
	try {
		spoilerVisibility.set(await api.get<SpoilerVisibility>('/ratings/spoiler-visibility'));
	} catch {
		// If the fetch fails (e.g. not authenticated), keep the current state
	}
}
