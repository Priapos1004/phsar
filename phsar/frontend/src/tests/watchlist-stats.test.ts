import { describe, it, expect } from 'vitest';
import type { WatchlistItem } from '$lib/types/api';
import { filterByPriority, filterByTags, sortRows, toAnimeRows, toMediaRows, toPriorityBands } from '$lib/utils/watchlistStats';

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

describe('filterByPriority', () => {
	const rows = toMediaRows([item({ priority: 1 }), item({ priority: 2 }), item({ priority: 3 })], LANG);

	it('returns all when no priorities selected', () => {
		expect(filterByPriority(rows, [])).toHaveLength(3);
	});

	it('returns the union of selected priority bands', () => {
		expect(filterByPriority(rows, [1, 3]).map((r) => r.priority).sort()).toEqual([1, 3]);
	});
});

describe('toMediaRows', () => {
	it('makes one row per entry with a single tag color', () => {
		const rows = toMediaRows([item({ media_title: 'X', tag_color: '#111', anime_title: 'Anime' })], LANG);
		expect(rows).toHaveLength(1);
		expect(rows[0].title).toBe('X');
		expect(rows[0].subtitle).toBe('Anime');
		expect(rows[0].mainSide).toBeNull(); // main/side is an anime-grain concept
		expect(rows[0].colors).toEqual(['#111']);
		expect(rows[0].spoilerMediaUuid).not.toBeNull();
	});

	it('flags note presence per media (noteCount 0/1)', () => {
		const rows = toMediaRows([item({ note: 'watch dubbed' }), item({ note: null })], LANG);
		expect(rows[0].note).toBe('watch dubbed');
		expect(rows[0].noteCount).toBe(1);
		expect(rows[1].noteCount).toBe(0);
	});
});

describe('toAnimeRows', () => {
	const items = [
		item({ anime_uuid: 'a1', anime_title: 'One', priority: 3, tag_uuid: 't1', tag_color: '#111', relation_type: 'main' }),
		item({ anime_uuid: 'a1', anime_title: 'One', priority: 1, tag_uuid: 't2', tag_color: '#222', relation_type: 'side_story' }),
		item({ anime_uuid: 'a2', anime_title: 'Two', priority: 2, tag_uuid: 't1', tag_color: '#111' }),
	];

	it('aggregates media into one row per anime with a main/side breakdown', () => {
		const rows = toAnimeRows(items, LANG);
		expect(rows).toHaveLength(2);
		const a1 = rows.find((r) => r.key === 'a1')!;
		expect(a1.mediaCount).toBe(2);
		expect(a1.subtitle).toBeNull(); // anime grain uses mainSide, not subtitle
		expect(a1.mainSide).toBe('1 main · 1 side');
	});

	it("counts how many of an anime's media carry a note and carries their texts", () => {
		const withNotes = [
			item({ anime_uuid: 'x', note: 'a' }),
			item({ anime_uuid: 'x', note: null }),
			item({ anime_uuid: 'x', note: 'b' }),
		];
		const x = toAnimeRows(withNotes, LANG).find((r) => r.key === 'x')!;
		expect(x.noteCount).toBe(2);
		expect(x.note).toBeNull(); // the single-note field isn't used at anime grain
		expect(x.noteTexts).toEqual(['a', 'b']); // texts are carried for the tooltip
	});

	it('orders noteTexts chronologically (year, season, mal_id) like the media table', () => {
		const notes = [
			item({ anime_uuid: 'x', note: 'fall-2021', anime_season_name: 'Fall', anime_season_year: 2021, mal_id: 5 }),
			item({ anime_uuid: 'x', note: 'winter-2020', anime_season_name: 'Winter', anime_season_year: 2020, mal_id: 9 }),
			item({ anime_uuid: 'x', note: 'spring-2020', anime_season_name: 'Spring', anime_season_year: 2020, mal_id: 3 }),
		];
		const x = toAnimeRows(notes, LANG).find((r) => r.key === 'x')!;
		expect(x.noteTexts).toEqual(['winter-2020', 'spring-2020', 'fall-2021']);
	});

	it('media grain leaves noteTexts empty (uses the note field instead)', () => {
		const rows = toMediaRows([item({ note: 'x' })], LANG);
		expect(rows[0].noteTexts).toEqual([]);
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

	it('sorts by note count (desc = most-noted first)', () => {
		const noteRows = toAnimeRows(
			[
				item({ anime_uuid: 'x', anime_title: 'X', note: 'a' }),
				item({ anime_uuid: 'x', anime_title: 'X', note: 'b' }),
				item({ anime_uuid: 'y', anime_title: 'Y', note: 'a' }),
				item({ anime_uuid: 'z', anime_title: 'Z', note: null }),
			],
			LANG,
		);
		expect(sortRows(noteRows, 'note', 'desc').map((r) => r.noteCount)).toEqual([2, 1, 0]);
	});

	it('keeps ties in a stable (title-ascending) order when the direction flips', () => {
		const tied = toMediaRows(
			[item({ media_title: 'Beta', priority: 2 }), item({ media_title: 'Alpha', priority: 2 })],
			LANG,
		);
		// Same priority → title-ascending both ways (Alpha before Beta), not reversed by dir.
		expect(sortRows(tied, 'priority', 'asc').map((r) => r.title)).toEqual(['Alpha', 'Beta']);
		expect(sortRows(tied, 'priority', 'desc').map((r) => r.title)).toEqual(['Alpha', 'Beta']);
	});
});
