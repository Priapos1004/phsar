import { describe, it, expect } from 'vitest';
import { computeVisibleMediaUuids } from '$lib/utils/spoilerFrontier';

function media(uuid: string, relation_type: string, year: number | null = null, season: string | null = null) {
	return { uuid, relation_type, anime_season_year: year, anime_season_name: season };
}

describe('computeVisibleMediaUuids', () => {
	it('returns empty set for empty input', () => {
		expect(computeVisibleMediaUuids([], new Set())).toEqual(new Set());
	});

	it('shows only first main when no ratings', () => {
		const items = [
			media('s1', 'main', 2020, 'Winter'),
			media('s2', 'main', 2021, 'Winter'),
			media('s3', 'main', 2022, 'Winter'),
		];
		const visible = computeVisibleMediaUuids(items, new Set());
		expect(visible).toEqual(new Set(['s1']));
	});

	it('shows first media if no main exists and no ratings', () => {
		const items = [
			media('ova', 'side_story', 2020),
			media('special', 'summary', 2021),
		];
		const visible = computeVisibleMediaUuids(items, new Set());
		expect(visible).toEqual(new Set(['ova']));
	});

	it('shows everything when all main rated', () => {
		const items = [
			media('s1', 'main', 2020),
			media('ova', 'side_story', 2020),
			media('s2', 'main', 2021),
		];
		const visible = computeVisibleMediaUuids(items, new Set(['s1', 's2']));
		expect(visible).toEqual(new Set(['s1', 'ova', 's2']));
	});

	it('frontier advances to next unrated main', () => {
		const items = [
			media('s1', 'main', 2020, 'Winter'),
			media('s2', 'main', 2021, 'Winter'),
			media('s3', 'main', 2022, 'Winter'),
			media('s4', 'main', 2023, 'Winter'),
			media('s5', 'main', 2024, 'Winter'),
		];
		const visible = computeVisibleMediaUuids(items, new Set(['s1', 's2']));
		expect(visible).toEqual(new Set(['s1', 's2', 's3']));
	});

	it('side stories between rated mains and frontier are visible', () => {
		const items = [
			media('s1', 'main', 2020, 'Winter'),
			media('s2', 'main', 2021, 'Winter'),
			media('ona', 'side_story', 2021, 'Summer'),
			media('sum', 'summary', 2021, 'Fall'),
			media('s3', 'main', 2022, 'Winter'),
			media('ova', 'side_story', 2022, 'Summer'),
			media('s4', 'main', 2023, 'Winter'),
		];
		const visible = computeVisibleMediaUuids(items, new Set(['s1', 's2']));
		// s1, s2 rated; ona, sum before frontier; s3 is frontier
		expect(visible).toEqual(new Set(['s1', 's2', 'ona', 'sum', 's3']));
	});

	it('single media anime with no rating shows it', () => {
		const items = [media('s1', 'main', 2023)];
		expect(computeVisibleMediaUuids(items, new Set())).toEqual(new Set(['s1']));
	});

	it('single media anime rated shows it', () => {
		const items = [media('s1', 'main', 2023)];
		expect(computeVisibleMediaUuids(items, new Set(['s1']))).toEqual(new Set(['s1']));
	});

	it('rating a side story does not advance frontier but rated media stays visible', () => {
		const items = [
			media('s1', 'main', 2020, 'Winter'),
			media('ova', 'side_story', 2020, 'Summer'),
			media('s2', 'main', 2021, 'Winter'),
		];
		const visible = computeVisibleMediaUuids(items, new Set(['ova']));
		// No main rated → frontier is first main (s1), but rated OVA also visible
		expect(visible).toEqual(new Set(['s1', 'ova']));
	});

	it('rated side story beyond frontier is visible', () => {
		const items = [
			media('s1', 'main', 2020, 'Winter'),
			media('s2', 'main', 2021, 'Winter'),
			media('ova', 'side_story', 2022, 'Winter'),
			media('s3', 'main', 2023, 'Winter'),
		];
		// s1 rated, ova rated (beyond frontier s2)
		const visible = computeVisibleMediaUuids(items, new Set(['s1', 'ova']));
		// frontier: s2 (next unrated main), ova rated → also visible, s3 hidden
		expect(visible).toEqual(new Set(['s1', 's2', 'ova']));
	});

	it('null seasons sort to end', () => {
		const items = [
			media('s1', 'main', 2020, 'Winter'),
			media('unknown', 'main', null, null),
			media('s2', 'main', 2021, 'Winter'),
		];
		// s1 rated → frontier is s2 (index 1 in sorted: s1, s2, unknown)
		const visible = computeVisibleMediaUuids(items, new Set(['s1']));
		expect(visible.has('s1')).toBe(true);
		expect(visible.has('s2')).toBe(true);
		expect(visible.has('unknown')).toBe(false);
	});
});
