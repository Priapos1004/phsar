import { describe, it, expect } from 'vitest';
import type { WatchlistItem } from '$lib/types/api';
import { filterByTags, sortRows, toAnimeRows, toMediaRows, toPriorityBands } from '$lib/utils/watchlistStats';

function item(overrides: Partial<WatchlistItem>): WatchlistItem {
	return {
		uuid: overrides.uuid ?? crypto.randomUUID(),
		media_uuid: overrides.media_uuid ?? crypto.randomUUID(),
		anime_uuid: overrides.anime_uuid ?? 'anime-1',
		media_title: overrides.media_title ?? 'M',
		media_name_eng: null,
		media_name_jap: null,
		anime_title: overrides.anime_title ?? 'A',
		anime_name_eng: null,
		anime_name_jap: null,
		media_cover_image: null,
		anime_cover_image: null,
		priority: overrides.priority ?? 3,
		note: overrides.note ?? null,
		tag_uuid: overrides.tag_uuid ?? 'tag-a',
		tag_name: overrides.tag_name ?? 'A',
		tag_color: overrides.tag_color ?? '#000000',
		relation_type: 'main',
		anime_season_name: null,
		anime_season_year: null,
		mal_id: overrides.mal_id ?? 1,
		created_at: overrides.created_at ?? '2024-01-01T00:00:00Z',
		modified_at: '2024-01-01T00:00:00Z',
		...overrides,
	};
}

const LANG = 'english' as const;

describe('filterByTags', () => {
	const items = [item({ tag_uuid: 'a' }), item({ tag_uuid: 'b' }), item({ tag_uuid: 'c' })];

	it('returns all when no tags selected', () => {
		expect(filterByTags(items, [])).toHaveLength(3);
	});

	it('returns the union of selected tags', () => {
		expect(filterByTags(items, ['a', 'c']).map((i) => i.tag_uuid).sort()).toEqual(['a', 'c']);
	});
});

describe('toMediaRows', () => {
	it('makes one row per entry with a single tag color', () => {
		const rows = toMediaRows([item({ media_title: 'X', tag_color: '#111', anime_title: 'Anime' })], LANG);
		expect(rows).toHaveLength(1);
		expect(rows[0].title).toBe('X');
		expect(rows[0].subtitle).toBe('Anime');
		expect(rows[0].colors).toEqual(['#111']);
		expect(rows[0].spoilerMediaUuid).not.toBeNull();
	});
});

describe('toAnimeRows', () => {
	const items = [
		item({ anime_uuid: 'a1', anime_title: 'One', priority: 3, tag_uuid: 't1', tag_color: '#111', relation_type: 'main' }),
		item({ anime_uuid: 'a1', anime_title: 'One', priority: 1, tag_uuid: 't2', tag_color: '#222', relation_type: 'side_story' }),
		item({ anime_uuid: 'a2', anime_title: 'Two', priority: 2, tag_uuid: 't1', tag_color: '#111' }),
	];

	it('aggregates media into one row per anime with a main/side subtitle', () => {
		const rows = toAnimeRows(items, LANG);
		expect(rows).toHaveLength(2);
		const a1 = rows.find((r) => r.key === 'a1')!;
		expect(a1.mediaCount).toBe(2);
		expect(a1.subtitle).toBe('1 main · 1 side');
	});

	it('uses the most-urgent (min) priority and distinct tag colors (gradient source)', () => {
		const a1 = toAnimeRows(items, LANG).find((r) => r.key === 'a1')!;
		expect(a1.priority).toBe(1);
		expect(a1.colors).toEqual(['#111', '#222']); // two distinct tags → gradient
		expect(a1.tagLabel).toBe('2 lists');
		expect(a1.spoilerMediaUuid).toBeNull(); // anime covers aren't spoiler-guarded
	});
});

describe('toPriorityBands', () => {
	const rows = toMediaRows(
		[
			item({ priority: 1, media_title: 'Zeta' }),
			item({ priority: 3, media_title: 'Alpha' }),
			item({ priority: 1, media_title: 'Alpha' }),
		],
		LANG,
	);

	it('drops empty bands and orders within a band by title', () => {
		const bands = toPriorityBands(rows, 'desc');
		expect(bands.map((b) => b.priority)).toEqual([1, 3]);
		expect(bands[0].rows.map((r) => r.title)).toEqual(['Alpha', 'Zeta']);
	});

	it('desc puts High first; asc flips it', () => {
		expect(toPriorityBands(rows, 'asc').map((b) => b.priority)).toEqual([3, 1]);
	});
});

describe('sortRows', () => {
	const rows = toMediaRows(
		[
			item({ media_title: 'B', priority: 1, created_at: '2024-03-01T00:00:00Z' }),
			item({ media_title: 'A', priority: 3, created_at: '2024-01-01T00:00:00Z' }),
		],
		LANG,
	);

	it('sorts by title, priority, and date', () => {
		expect(sortRows(rows, 'title', 'asc').map((r) => r.title)).toEqual(['A', 'B']);
		expect(sortRows(rows, 'priority', 'asc').map((r) => r.priority)).toEqual([1, 3]);
		expect(sortRows(rows, 'date', 'desc').map((r) => r.createdAt)).toEqual([
			'2024-03-01T00:00:00Z',
			'2024-01-01T00:00:00Z',
		]);
	});
});
