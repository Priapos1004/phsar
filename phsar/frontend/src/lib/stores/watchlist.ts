import { writable, derived } from 'svelte/store';
import { api } from '$lib/api';
import type { WatchlistMediaTag, WatchlistMediaTags } from '$lib/types/api';

// media UUID → the tag it's watchlisted under. Drives the bookmark icon state
// (present/absent) AND the tag color the bookmark renders in, everywhere a media
// appears (media page, anime page, search cards). Mirrors the spoilerVisibility
// store; refreshed on login + after any watchlist mutation.
export const watchlistTags = writable<Map<string, WatchlistMediaTag>>(new Map());

// anime UUID → its distinct watchlisted tag colors (dedup by tag, preserving first-seen
// order). One color → a solid bookmark; several → a gradient. Drives the anime-level
// bookmark on anime search cards + the anime hero (an anime can span multiple tags).
export const watchlistAnimeColors = derived(watchlistTags, ($map) => {
	const byAnime = new Map<string, string[]>();
	const seenTag = new Map<string, Set<string>>();
	for (const e of $map.values()) {
		let colors = byAnime.get(e.anime_uuid);
		let tags = seenTag.get(e.anime_uuid);
		if (!colors) {
			colors = [];
			byAnime.set(e.anime_uuid, colors);
			tags = new Set();
			seenTag.set(e.anime_uuid, tags);
		}
		if (!tags!.has(e.tag_uuid)) {
			tags!.add(e.tag_uuid);
			colors.push(e.tag_color);
		}
	}
	return byAnime;
});

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
