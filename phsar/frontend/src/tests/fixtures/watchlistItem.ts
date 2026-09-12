import type { WatchlistItem } from '$lib/types/api';

/** A `/watchlist/items` entry with every field defaulted, so a test states only the
 *  fields it is about. Shared by the stats and readiness suites — a 25-field builder
 *  copied per suite is one that drifts when the DTO gains a field. */
export function watchlistItem(overrides: Partial<WatchlistItem> = {}): WatchlistItem {
	return {
		uuid: crypto.randomUUID(),
		media_uuid: crypto.randomUUID(),
		anime_uuid: 'anime-1',
		media_title: 'M',
		media_name_eng: null,
		media_name_jap: null,
		anime_title: 'A',
		anime_name_eng: null,
		anime_name_jap: null,
		media_cover_image: null,
		anime_cover_image: null,
		priority: 3,
		note: null,
		tag_uuid: 'tag-a',
		tag_name: 'A',
		tag_color: '#000000',
		relation_type: 'main',
		anime_season_name: null,
		anime_season_year: null,
		mal_id: 1,
		// Defaults describe the plainly-ready case: a finished, unrated media in a
		// franchise with nothing airing and nothing announced. Every readiness test
		// then reads as one deviation from "ready".
		airing_status: 'Finished Airing',
		watch_status: null,
		franchise_airing: false,
		franchise_upcoming_key: null,
		genres: [],
		studios: [],
		total_watch_time: null,
		created_at: '2024-01-01T00:00:00Z',
		modified_at: '2024-01-01T00:00:00Z',
		...overrides,
	};
}
