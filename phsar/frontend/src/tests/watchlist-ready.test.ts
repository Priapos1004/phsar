// The readiness rules, case by case. docs/features/readiness.md carries the same table
// in prose; this is the executable copy, and the one that fails when a rule moves.
//
// Every test fixes `now` to Summer 2026, so "next season" is Fall 2026 and the horizon
// never depends on when the suite runs.
import { describe, it, expect } from 'vitest';
import { watchlistItem as item } from './fixtures/watchlistItem';
import {
	animeStatus,
	isAvailable,
	isReady,
	mediaClass,
	statusByAnime,
	STANDALONE_SECONDS,
} from '$lib/utils/watchlistReady';
import { filterByReadiness } from '$lib/utils/watchlistStats';
import { nextSeasonKey, seasonKey } from '$lib/utils/getSeason';

const NOW = new Date('2026-08-15T00:00:00Z'); // Summer 2026 → next season is Fall 2026

const aired = (o = {}) => item({ airing_status: 'Finished Airing', ...o });
const airing = (o = {}) => item({ airing_status: 'Currently Airing', ...o });
const unaired = (season: string | null, year: number | null, o = {}) =>
	item({ airing_status: 'Not yet aired', anime_season_name: season, anime_season_year: year, ...o });

describe('seasonKey / nextSeasonKey', () => {
	it('encodes a season the way the backend does', () => {
		// The backend half of this pins the same literal in
		// tests/routers/test_watchlist.py::test_franchise_upcoming_key_takes_the_earliest_announced_season.
		// No import spans Python and TypeScript, so these two assertions are the only
		// thing holding the encoding together — change one and change the other.
		expect(seasonKey('Fall', 2026)).toBe(2026 * 10 + 4);
		expect(seasonKey('Winter', 2027)).toBe(2027 * 10 + 1);
		expect(seasonKey('Fall', 2026)!).toBeLessThan(seasonKey('Winter', 2027)!);
	});

	it('has no key for an unknown season, rather than one that sorts first', () => {
		expect(seasonKey(null, 2027)).toBeNull();
		expect(seasonKey('Fall', null)).toBeNull();
	});

	it('rolls Fall into the next Winter', () => {
		expect(nextSeasonKey(new Date('2026-08-15'))).toBe(seasonKey('Fall', 2026));
		expect(nextSeasonKey(new Date('2026-11-15'))).toBe(seasonKey('Winter', 2027));
	});
});

describe('mediaClass', () => {
	it.each([
		['finished → aired', aired(), 'aired'],
		['airing now', airing(), 'airing'],
		['this season, still marked unaired (stale scrape)', unaired('Summer', 2026), 'soon'],
		['next season', unaired('Fall', 2026), 'soon'],
		['two seasons out', unaired('Winter', 2027), 'later'],
		['no announced season', unaired(null, null), 'tba'],
	])('%s', (_label, entry, expected) => {
		expect(mediaClass(entry, NOW)).toBe(expected);
	});

	it('only finished media can be played, whether or not it was rated', () => {
		expect(isAvailable(aired({ watch_status: 'completed' }), NOW)).toBe(true);
		expect(isAvailable(unaired('Winter', 2027), NOW)).toBe(false);
	});
});

describe('animeStatus — the case table', () => {
	const cases: [string, ReturnType<typeof item>[], string][] = [
		// A — is there something to watch?
		['a lone unwatched finished season', [aired()], 'ready'],
		['a finished season already rated, i.e. a rewatch', [aired({ watch_status: 'completed' })], 'ready'],
		[
			'everything watched, with a far-off sequel listed — nothing new to watch',
			[aired({ watch_status: 'completed' }), unaired('Winter', 2028, {})],
			'waiting',
		],
		[
			'everything watched but one finished part still unwatched, sequel far off',
			[
				aired({ watch_status: 'completed' }),
				aired({ watch_status: null }),
				unaired('Winter', 2028, {}),
			],
			'ready',
		],
		['nothing but future bookmarks', [unaired('Winter', 2028, {})], 'waiting'],

		// B1 — nothing YOU listed is airing or imminent.
		['a listed season airing right now', [aired(), airing()], 'hot'],
		['a listed season due next season', [aired(), unaired('Fall', 2026)], 'hot'],
		['a listed season two seasons out does not block', [aired(), unaired('Winter', 2027)], 'ready'],
		[
			'dropping a season you listed does NOT unblock it',
			[aired(), airing({ watch_status: 'dropped' })],
			'hot',
		],
		[
			'a listed upcoming OVA is not a season you wait for',
			[aired(), unaired('Fall', 2026, { relation_type: 'side_story' })],
			'ready',
		],

		// B2 — the franchise, including media never listed.
		['an unlisted sequel airing now blocks', [aired({ franchise_airing: true })], 'hot'],
		[
			'an unlisted sequel due next season blocks',
			[aired({ franchise_upcoming_key: seasonKey('Fall', 2026) })],
			'hot',
		],
		[
			'an unlisted sequel two seasons out does not',
			[aired({ franchise_upcoming_key: seasonKey('Winter', 2027) })],
			'ready',
		],
	];

	it.each(cases)('%s → %s', (_label, items, expected) => {
		expect(animeStatus(items, NOW)).toBe(expected);
	});
});

describe('the standalone rule', () => {
	const HOURS = 3600;

	it('lets one long entry stand alone against an airing franchise', () => {
		// Dragon Ball's classic run is 61h in a single media.
		const items = [aired({ franchise_airing: true, total_watch_time: 61 * HOURS })];
		expect(animeStatus(items, NOW)).toBe('standalone');
		expect(isReady(animeStatus(items, NOW))).toBe(true);
	});

	it('is per media, not summed — a long story split into short seasons does not qualify', () => {
		// Boku no Hero shaped: 7 seasons of 10h each. 70h in total, but you would still
		// want the new season, so summing here would give the wrong answer.
		const items = Array.from({ length: 7 }, () =>
			aired({ franchise_airing: true, total_watch_time: 10 * HOURS }),
		);
		expect(animeStatus(items, NOW)).toBe('hot');
	});

	it('holds at the boundary', () => {
		const at = (seconds: number) => animeStatus([aired({ franchise_airing: true, total_watch_time: seconds })], NOW);
		expect(at(STANDALONE_SECONDS - 1)).toBe('hot');
		expect(at(STANDALONE_SECONDS)).toBe('standalone');
	});

	it('never fires on an open-ended show, whose runtime is unknown', () => {
		expect(animeStatus([aired({ franchise_airing: true, total_watch_time: null })], NOW)).toBe('hot');
	});

	it('does not rescue a season you listed yourself', () => {
		// B1 has no standalone exemption: listing the airing season means you want it.
		const items = [aired({ total_watch_time: 61 * HOURS }), airing()];
		expect(animeStatus(items, NOW)).toBe('hot');
	});
});

describe('filterByReadiness', () => {
	const readyAnime = [
		aired({ anime_uuid: 'ready', watch_status: 'completed' }),
		aired({ anime_uuid: 'ready' }),
		unaired('Winter', 2028, { anime_uuid: 'ready' }),
	];
	const hotAnime = [aired({ anime_uuid: 'hot' }), airing({ anime_uuid: 'hot' })];
	const all = [...readyAnime, ...hotAnime];
	const statuses = statusByAnime(all, NOW);
	const uuids = (items: ReturnType<typeof item>[]) => [...new Set(items.map((i) => i.anime_uuid))];

	it('shows everything when no chip is selected', () => {
		expect(filterByReadiness(all, statuses, [], 'anime', NOW)).toHaveLength(all.length);
	});

	it('drops every entry of an anime outside the selection', () => {
		const kept = filterByReadiness(all, statuses, ['ready'], 'anime', NOW);
		expect(uuids(kept)).toEqual(['ready']);
		expect(kept).toHaveLength(3);
	});

	it('unions the chips, like the tag and priority filters', () => {
		expect(uuids(filterByReadiness(all, statuses, ['ready', 'hot'], 'anime', NOW)).sort()).toEqual([
			'hot',
			'ready',
		]);
	});

	it('admits a standalone anime under the Ready chip', () => {
		// Standalone is a flavour of ready, not a chip of its own.
		const long = [aired({ anime_uuid: 's', franchise_airing: true, total_watch_time: 61 * 3600 })];
		expect(animeStatus(long, NOW)).toBe('standalone');
		expect(filterByReadiness(long, statusByAnime(long, NOW), ['ready'], 'anime', NOW)).toHaveLength(1);
	});

	it('narrows a READY anime at media grain to what can be played, rewatches included', () => {
		const kept = filterByReadiness(all, statuses, ['ready'], 'media', NOW);
		// The 2028 entry drops (unplayable); the already-rated one stays (a rewatch).
		expect(kept).toHaveLength(2);
		expect(kept.every((i) => i.airing_status === 'Finished Airing')).toBe(true);
	});

	it('keeps every entry of a HOT anime at media grain, because there the airing one is the answer', () => {
		const kept = filterByReadiness(all, statuses, ['hot'], 'media', NOW);
		expect(kept).toHaveLength(2);
		expect(kept.some((i) => i.airing_status === 'Currently Airing')).toBe(true);
	});

	it('judges an anime on its whole watchlist, not the visible subset', () => {
		// The airing season sits on a different list. Filtering to the other list must not
		// make the franchise look ready — otherwise parking blockers elsewhere unblocks it.
		const spread = [
			aired({ anime_uuid: 'x', tag_uuid: 'binge' }),
			airing({ anime_uuid: 'x', tag_uuid: 'ongoing' }),
		];
		const full = statusByAnime(spread, NOW);
		const visible = spread.filter((i) => i.tag_uuid === 'binge');
		expect(filterByReadiness(visible, full, ['ready'], 'anime', NOW)).toHaveLength(0);
	});
});
