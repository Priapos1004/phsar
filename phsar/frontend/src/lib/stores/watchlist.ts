import { writable, derived } from 'svelte/store';
import { api } from '$lib/api';
import type { WatchlistMediaTag, WatchlistMediaTags } from '$lib/types/api';

// media UUID → the tag it's watchlisted under. Drives the bookmark icon state
// (present/absent) AND the tag color the bookmark renders in, everywhere a media
// appears (media page, anime page, search cards). Mirrors the spoilerVisibility
// store; refreshed on login + after any watchlist mutation.
export const watchlistTags = writable<Map<string, WatchlistMediaTag>>(new Map());

/** `(mediaUuid) => WatchlistMediaTag | undefined` — the entry's tag, or undefined
 *  if the media isn't watchlisted. `!!` it for a boolean, read `.tag_color` to color. */
export const watchlistTagFor = derived(
	watchlistTags,
	($map) => (mediaUuid: string) => $map.get(mediaUuid)
);

/** Re-fetch the watchlisted-media→tag set. Call after any watchlist add/remove. */
export async function refreshWatchlist(): Promise<void> {
	try {
		const res = await api.get<WatchlistMediaTags>('/watchlist/media-tags');
		watchlistTags.set(new Map(res.entries.map((e) => [e.media_uuid, e])));
	} catch {
		// Not authenticated / restricted user / transient error — keep current state.
	}
}

/** Clear on logout / user switch. */
export function clearWatchlist(): void {
	watchlistTags.set(new Map());
}
